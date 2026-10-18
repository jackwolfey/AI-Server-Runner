"""GGUF 文件元数据解析（纯标准库实现）+ 显存粗估。"""

import re
import struct

GGUF_MAGIC = 0x46554747

# GGUF 定宽值类型 → 字节宽度（用于大数组 seek 快速跳过）
_GGUF_FIXED_SIZE = {
    0: 1, 1: 1,           # uint8, int8
    2: 2, 3: 2,           # uint16, int16
    4: 4, 5: 4,           # uint32, int32
    6: 4, 7: 1,           # float32, bool
    10: 8, 11: 8, 12: 8,  # uint64, int64, float64
}

_FILE_TYPE_QUANT = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0",
    9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L",
    14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K",
    19: "IQ2_XXS", 20: "IQ2_XS", 21: "IQ3_XXS", 22: "IQ1_S",
    23: "IQ4_NL", 24: "IQ3_S", 25: "IQ2_S", 26: "IQ4_XS", 28: "IQ1_M",
    30: "BF16",
}

_QUANT_NAME_RE = re.compile(
    r"(?:^|[-_.])((?:IQ|Q)\d+(?:_[A-Z0-9]+)*|F16|F32|BF16)(?=\.|-|$)",
    re.IGNORECASE)

_PARAM_NAME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([BbMm])")


def _read_gguf_string(f):
    """读取一个 GGUF 字符串（uint64 长度前缀 + UTF-8 字节）。"""
    length = struct.unpack("<Q", f.read(8))[0]
    if length > 10 * 1024 * 1024:  # 防御异常长度
        raise ValueError(f"字符串长度异常: {length}")
    data = f.read(length)
    return data.decode("utf-8", errors="replace")


def _read_gguf_value(f, vtype):
    """按 GGUF 元数据类型编号读取一个值。支持全部 13 种类型（含递归数组）。"""
    if vtype == 0:  # uint8
        return struct.unpack("<B", f.read(1))[0]
    if vtype == 1:  # int8
        return struct.unpack("<b", f.read(1))[0]
    if vtype == 2:  # uint16
        return struct.unpack("<H", f.read(2))[0]
    if vtype == 3:  # int16
        return struct.unpack("<h", f.read(2))[0]
    if vtype == 4:  # uint32
        return struct.unpack("<I", f.read(4))[0]
    if vtype == 5:  # int32
        return struct.unpack("<i", f.read(4))[0]
    if vtype == 6:  # float32
        return struct.unpack("<f", f.read(4))[0]
    if vtype == 7:  # bool
        return bool(struct.unpack("<B", f.read(1))[0])
    if vtype == 8:  # string
        return _read_gguf_string(f)
    if vtype == 9:  # array
        elem_type = struct.unpack("<I", f.read(4))[0]
        elem_count = struct.unpack("<Q", f.read(8))[0]
        esize = _GGUF_FIXED_SIZE.get(elem_type)
        if esize is not None:
            # 定宽元素：大数组直接 seek 跳过（如 tokenizer 分数表），
            # 避免逐元素读取拖慢扫描
            if elem_count > 10000:
                f.seek(elem_count * esize, 1)
                return None
            return [_read_gguf_value(f, elem_type) for _ in range(elem_count)]
        # 变长元素（字符串/嵌套数组）：无法直接跳过，只能逐个读但丢弃
        if elem_count > 10000:
            for _ in range(elem_count):
                _read_gguf_value(f, elem_type)
            return None
        return [_read_gguf_value(f, elem_type) for _ in range(elem_count)]
    if vtype == 10:  # uint64
        return struct.unpack("<Q", f.read(8))[0]
    if vtype == 11:  # int64
        return struct.unpack("<q", f.read(8))[0]
    if vtype == 12:  # float64
        return struct.unpack("<d", f.read(8))[0]
    raise ValueError(f"未知 GGUF 值类型: {vtype}")


def parse_gguf_metadata(path):
    """解析 GGUF 文件头部元数据（不加载权重张量）。
    返回 dict；非 GGUF 文件 / 版本过老 / 解析失败返回 None。
    仅读取文件头部若干 MB，对大模型文件开销极小。"""
    try:
        with open(path, "rb") as f:
            magic = struct.unpack("<I", f.read(4))[0]
            if magic != GGUF_MAGIC:
                return None
            version = struct.unpack("<I", f.read(4))[0]
            if version < 2:
                return None  # v1 布局不同，暂不支持
            tensor_count = struct.unpack("<Q", f.read(8))[0]
            kv_count = struct.unpack("<Q", f.read(8))[0]
            if kv_count > 100000:
                return None
            metadata = {}
            for _ in range(kv_count):
                key = _read_gguf_string(f)
                vtype = struct.unpack("<I", f.read(4))[0]
                try:
                    value = _read_gguf_value(f, vtype)
                except Exception:
                    value = None
                metadata[key] = value
            return metadata
    except (OSError, ValueError, struct.error):
        return None


def _quant_from_file_type(ft):
    if isinstance(ft, int):
        return _FILE_TYPE_QUANT.get(ft)
    return None


def _guess_quant_from_name(filename):
    m = _QUANT_NAME_RE.search(filename)
    return m.group(1).upper() if m else "-"


def _guess_params_from_name(filename):
    m = _PARAM_NAME_RE.search(filename)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}"
    return "-"


def extract_gguf_info(metadata, file_size, filename):
    """从 GGUF 元数据提取面向显示的结构化信息 dict。"""
    if not metadata:
        return {
            "quant": _guess_quant_from_name(filename),
            "ctx_limit": None, "n_layers": None, "n_embd": None,
            "params": _guess_params_from_name(filename),
            "arch": None, "name": None,
        }
    arch = metadata.get("general.architecture")
    ctx = metadata.get(f"{arch}.context_length") if arch else None
    layers = metadata.get(f"{arch}.block_count") if arch else None
    emb = metadata.get(f"{arch}.embedding_length") if arch else None
    n_heads = metadata.get(f"{arch}.attention.head_count") if arch else None
    n_kv = metadata.get(f"{arch}.attention.head_count_kv", n_heads) if arch else None
    size_label = metadata.get("general.size_label")
    name = metadata.get("general.name")
    file_type = metadata.get("general.file_type")
    quant = _quant_from_file_type(file_type) or _guess_quant_from_name(filename)
    params = size_label or _guess_params_from_name(filename)
    return {
        "quant": quant, "ctx_limit": ctx, "n_layers": layers, "n_embd": emb,
        "n_heads": n_heads, "n_kv_heads": n_kv,
        "params": params, "arch": arch, "name": name,
    }


def estimate_vram_gb(file_size_bytes, ctx, info):
    """粗略估算「全量 GPU 卸载」时的显存占用。
    返回 (权重GB, KV缓存GB, 合计GB)。ctx 为 None 时 KV 记 0。
    公式：KV = 2(K+V) × layers × ctx × head_dim × n_kv_heads × 2字节(fp16)。
    实际占用还受 llama-server 内部缓冲、MoE、量化 KV 等影响，仅供粗略参考。"""
    weights_gb = file_size_bytes / (1024 ** 3)
    if not ctx or not info:
        return weights_gb, 0.0, weights_gb
    layers = info.get("n_layers")
    emb = info.get("n_embd")
    n_heads = info.get("n_heads")
    n_kv = info.get("n_kv_heads") or n_heads
    if not (layers and emb and n_heads and n_kv):
        return weights_gb, 0.0, weights_gb
    head_dim = emb / n_heads
    kv_bytes = 2 * layers * ctx * head_dim * n_kv * 2
    kv_gb = kv_bytes / (1024 ** 3)
    return weights_gb, kv_gb, weights_gb + kv_gb
