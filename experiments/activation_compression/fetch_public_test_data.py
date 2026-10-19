"""Collect the public Beer/can test split and two OTB sequences for local tests."""

import argparse
import hashlib
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from urllib.request import urlopen

from PIL import Image

PROJECT = "https://studio.edgeimpulse.com/public/89078/latest/acquisition/testing"
OTB = {
    "Coke": ("1nGsvt_IImvA4iJD22Qzm9jFPJxi-AudA", "3158a246da79646d0ef86bde44761d77c8d2df89cfb287ff25aa536f187a520b"),
    "Liquor": ("1npRoxKorlgVqnf7fYtDkPrJ4pPBLQO1u", "75632ad053e87c3b9bfd55916ac576d9eb7ea0cc6cc614bcbbdf8f9dc704469a"),
}


class DatasetPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.data = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and "value" in attrs:
            try:
                data = json.loads(unquote(attrs["value"]))
            except (ValueError, TypeError):
                return
            if isinstance(data, dict) and "dataset" in data and "rows" in data:
                self.data = data


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    with urlopen(url, timeout=60) as response, temporary.open("wb") as output:
        while block := response.read(1024 * 1024):
            output.write(block)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    samples, pages, page = {}, None, 1
    while pages is None or page <= pages:
        with urlopen(f"{PROJECT}?page={page}", timeout=30) as response:
            html = response.read().decode()
        parsed = DatasetPage()
        parsed.feed(html)
        if not parsed.data or parsed.data["category"] != "testing":
            raise ValueError("Public test page format/category changed")
        data = parsed.data
        pages = data["pagination"]["pageCount"]
        for row in data["rows"]:
            if row["category"] != "testing" or row["isDisabled"]:
                continue
            sample_id, project_id = int(row["id"]), int(row["projectId"])
            samples[sample_id] = {
                "id": sample_id, "source_project_id": project_id, "source_name": row["filename"],
                "source_category": "testing", "bounding_boxes": row["boundingBoxes"],
                "image_dimensions": row["imageDimensions"],
                "url": f"https://studio.edgeimpulse.com/v1/api/{project_id}/raw-data/{sample_id}/image?datastreamIndex=0",
                "path": f"edgeimpulse_test/{sample_id}.jpg",
            }
        page += 1
    expected_count = data["itemCount"]["filtered"]
    if len(samples) != expected_count:
        raise ValueError(f"Incomplete public split: {len(samples)} / {expected_count}")

    def image_sample(item):
        path = out / item["path"]
        if not path.exists():
            fetch(item["url"], path)
        with Image.open(path) as image:
            assert image.size == (item["image_dimensions"]["width"], item["image_dimensions"]["height"])
            image.verify()
        return dict(item, sha256=digest(path), bytes=path.stat().st_size)

    with ThreadPoolExecutor(max_workers=4) as pool:
        images = list(pool.map(image_sample, sorted(samples.values(), key=lambda row: row["id"])))
    print(f"Downloaded and verified {len(images)} public test images", flush=True)
    sequences = []
    for name, (source_id, expected) in OTB.items():
        url = f"https://drive.usercontent.google.com/download?id={source_id}&export=download&confirm=t"
        path = out / "otb" / f"{name}.zip"
        if not path.exists():
            fetch(url, path)
        if digest(path) != expected:
            raise ValueError(f"Source archive changed or download is not ZIP: {name}")
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"ZIP CRC failure: {name}")
            frames = sorted(n for n in archive.namelist() if n.lower().endswith(".jpg"))
            annotations = [n for n in archive.namelist() if n.endswith("groundtruth_rect.txt")]
        sequences.append({"name": name, "path": path.relative_to(out).as_posix(), "url": url,
                          "sha256": expected, "bytes": path.stat().st_size, "frames": len(frames),
                          "frame_members": frames, "tracking_annotation_members": annotations,
                          "original_fps_verified": False})
        print(f"Verified {name}: {len(frames)} frames", flush=True)
    manifest = {
        "created_utc": datetime.now(UTC).isoformat(), "edgeimpulse_test_source": PROJECT,
        "otb_source": "https://rvlab.snu.ac.kr/research/tracker_benchmark",
        "edgeimpulse_test_images": images, "otb_sequences": sequences,
        "limits": ["Public project test split; relationship to local H5 training history not proven",
                   "Independent photos are not a temporal sequence",
                   "OTB annotations track targets, not exhaustive Beer/can class annotations",
                   "Original OTB frame rate not verified; do not invent fps"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(out / "manifest.json")


if __name__ == "__main__":
    main()
