"""Vision model integration for map analysis.

Uses a multimodal model (llama3.2-vision) to analyze dungeon maps
and extract spatial understanding. Results are cached per-map so we
only run vision inference once per floor, not every turn.
"""

import json
import hashlib
from pathlib import Path

import ollama


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "maps" / "_vision_cache"


class MapVision:
    """Analyzes dungeon maps using a vision model."""

    def __init__(
        self,
        model: str = "llama3.2-vision:11b",
        base_url: str = "http://localhost:11434",
    ):
        self.model = model
        self.client = ollama.Client(host=base_url)
        self._cache: dict[str, str] = {}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def check_available(self) -> bool:
        """Check if the vision model is available."""
        try:
            response = self.client.list()
            models = response.models if hasattr(response, "models") else response.get("models", [])
            for m in models:
                name = getattr(m, "model", None) or (m.get("name", "") if isinstance(m, dict) else "")
                if self.model in name:
                    return True
            return False
        except Exception:
            return False

    def analyze_map(self, image_path: str, floor_label: str, module_name: str = "") -> str:
        """Analyze a map image and return a spatial description.

        Results are cached to disk so we don't re-analyze on every server restart.
        """
        # Check cache
        cache_key = self._cache_key(image_path)
        cached = self._load_cache(cache_key)
        if cached:
            return cached

        # Read image
        img_path = Path(image_path)
        if not img_path.exists():
            return ""

        with open(img_path, "rb") as f:
            img_data = f.read()

        prompt = f"""You are analyzing a tabletop RPG dungeon map for a Dungeon Master.
This is the {floor_label} of {module_name or 'a dungeon'}. 1 square = 10 feet. This is a top-down floor plan of a SINGLE FLOOR.

Study this map carefully and describe:

1. ENTRANCES/EXITS: Where can you enter this floor? Mark compass directions (N/S/E/W).
2. MAJOR AREAS: Identify the largest rooms and open areas. Describe their shape and approximate position.
3. CORRIDORS: How do the main corridors connect the different areas? Are there long hallways, tight passages?
4. TOWERS: Identify any round/circular rooms — these are towers. Where are they on the map?
5. STAIRCASES: Look for staircase symbols (parallel lines, spiral patterns). Where do they go (up/down)?
6. COURTYARDS: Any outdoor areas (shown with trees/gardens)?
7. LAYOUT FLOW: If someone enters from the main entrance, describe the general flow — what areas do they reach first, and how does the layout branch?

Be specific about spatial positions. Use compass directions. Do NOT invent rooms that aren't visible."""

        try:
            response = self.client.chat(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": prompt,
                    "images": [img_data],
                }],
                options={"temperature": 0.2, "num_ctx": 4096},
            )
            result = response.message.content
        except Exception as e:
            return f"(Vision analysis failed: {e})"

        # Cache the result
        self._save_cache(cache_key, result)
        self._cache[cache_key] = result

        return result

    def analyze_room_area(self, image_path: str, room_id: str, room_name: str, section_name: str) -> str:
        """Analyze a specific area of the map focused on a room's surroundings.

        This is lighter-weight than full map analysis — focuses on exits and adjacent areas.
        """
        cache_key = self._cache_key(f"{image_path}_{room_id}")
        cached = self._load_cache(cache_key)
        if cached:
            return cached

        img_path = Path(image_path)
        if not img_path.exists():
            return ""

        with open(img_path, "rb") as f:
            img_data = f.read()

        prompt = f"""This is a dungeon map. I need you to find room {room_id} ({room_name}) in the {section_name} section.

Look at the map and tell me:
1. How many exits/doors does this room have?
2. What directions do they lead (N/S/E/W)?
3. Are any doors marked as secret (hidden, dashed lines)?
4. What rooms or corridors are immediately adjacent?
5. Is there a staircase in or near this room?

Only describe what you can actually see on the map. Be brief and precise."""

        try:
            response = self.client.chat(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": prompt,
                    "images": [img_data],
                }],
                options={"temperature": 0.2, "num_ctx": 2048},
            )
            result = response.message.content
        except Exception as e:
            return ""

        self._save_cache(cache_key, result)
        return result

    def _cache_key(self, identifier: str) -> str:
        return hashlib.md5(f"{self.model}:{identifier}".encode()).hexdigest()

    def _load_cache(self, key: str) -> str | None:
        if key in self._cache:
            return self._cache[key]
        cache_file = CACHE_DIR / f"{key}.txt"
        if cache_file.exists():
            text = cache_file.read_text()
            self._cache[key] = text
            return text
        return None

    def _save_cache(self, key: str, text: str) -> None:
        self._cache[key] = text
        cache_file = CACHE_DIR / f"{key}.txt"
        cache_file.write_text(text)


def preanalyze_module_maps(
    module_dir: str | Path,
    vision: MapVision,
    module_name: str = "",
) -> dict[str, str]:
    """Pre-analyze all maps for a module. Returns {map_key: analysis_text}."""
    module_dir = Path(module_dir)
    data_file = module_dir / "map_data.json"
    if not data_file.exists():
        return {}

    with open(data_file) as f:
        data = json.load(f)

    module_name = module_name or data.get("module", "Unknown")
    results = {}

    for map_key, map_info in data.get("maps", {}).items():
        image_file = module_dir / map_info["file"]
        if image_file.exists():
            label = map_info.get("label", map_key)
            print(f"  Analyzing {label}...")
            analysis = vision.analyze_map(str(image_file), label, module_name)
            results[map_key] = analysis

    return results
