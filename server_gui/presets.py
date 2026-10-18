"""预设配置存取（llama_gui_presets.json）。"""

import json
import os


class PresetStore:
    """管理 llama_gui_presets.json 的读写。path 为 None 时只做内存操作。"""

    def __init__(self, path=None):
        self.path = path
        self.warnings = []
        self.data = {"presets": []}
        self.load()

    def load(self):
        self.warnings = []
        self.data = {"presets": []}
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self.warnings.append(f"预设文件读取失败（已按空处理）：{e}")
            return
        presets = raw.get("presets") if isinstance(raw, dict) else None
        if not isinstance(presets, list):
            self.warnings.append("预设文件格式不正确（缺少 presets 列表），已按空处理。")
            return
        cleaned = []
        for i, p in enumerate(presets):
            if not isinstance(p, dict):
                self.warnings.append(f"第 {i + 1} 项预设格式不正确，已跳过。")
                continue
            item = {
                "name": str(p.get("name") or ""),
                "model": str(p.get("model") or ""),
                "args": str(p.get("args") or ""),
            }
            comfy = p.get("comfy")
            if isinstance(comfy, dict):
                item["comfy"] = {
                    "python": str(comfy.get("python") or ""),
                    "main": str(comfy.get("main") or ""),
                    "args": str(comfy.get("args") or ""),
                }
            cleaned.append(item)
        self.data = {"presets": cleaned}

    def save(self):
        if not self.path:
            return False, "未设置有效的工作目录，无法保存预设。"
        try:
            folder = os.path.dirname(self.path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True, self.path
        except OSError as e:
            return False, str(e)

    @property
    def items(self):
        return self.data["presets"]

    def add_or_update(self, name, model, args, comfy=None):
        for p in self.items:
            if p["name"] == name:
                p["model"] = model
                p["args"] = args
                if comfy is not None:
                    p["comfy"] = comfy
                return "updated"
        item = {"name": name, "model": model, "args": args}
        if comfy is not None:
            item["comfy"] = comfy
        self.items.append(item)
        return "added"

    def remove_at(self, index):
        if 0 <= index < len(self.items):
            return self.items.pop(index)
        return None

    def index_of(self, name):
        for i, p in enumerate(self.items):
            if p["name"] == name:
                return i
        return -1

    def move(self, index, offset):
        items = self.items
        if not (0 <= index < len(items)):
            return index
        new_index = index + offset
        if not (0 <= new_index < len(items)):
            return index
        items[index], items[new_index] = items[new_index], items[index]
        return new_index

    def rename(self, index, new_name):
        items = self.items
        if not (0 <= index < len(items)):
            return False, "预设不存在。"
        new_name = (new_name or "").strip()
        if not new_name:
            return False, "预设名称不能为空。"
        for i, p in enumerate(items):
            if i != index and p["name"] == new_name:
                return False, f"已存在同名预设「{new_name}」，请换一个名称。"
        items[index]["name"] = new_name
        return True, new_name
