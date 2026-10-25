"""Task and image persistence through the owner-scoped session repository."""
import time
import uuid

import requests


class Persist:
    def __init__(self, store):
        self.store = store

    def save_task_state(self, task_id, state):
        self.store.set_state(task_id, state)
        self.store.flush(task_id)

    def save_image(self, task_id, episode_number, storyboard_index, shot, scene,
                   prompt, image_url, kind="", character_name=""):
        image_id = task_id + "." + uuid.uuid4().hex
        row = dict(id=image_id, task_id=task_id, episode_number=episode_number,
                   storyboard_index=storyboard_index, shot=shot, scene=scene,
                   prompt=prompt, image_url=image_url, kind=kind,
                   character_name=character_name, created_at=time.time())
        if image_url.startswith(("https://", "http://")):
            with requests.get(image_url, timeout=(5, 20), stream=True) as res:
                res.raise_for_status()
                data = bytearray()
                for chunk in res.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 20 * 1024 * 1024:
                        raise ValueError("Image exceeds 20 MB")
                self.cache_image(image_id, bytes(data))
            row["image_url"] = f"/api/sessions/{task_id}/images/{image_id.split('.')[1]}"
        with self.store._lock:
            self.store._sessions[task_id]["doc"]["images"].append(row)
            self.store.flush(task_id)
        return row["image_url"]

    def image_key(self, image_id):
        sid, iid = image_id.split(".")
        owner = self.store._sessions[sid]["doc"]["owner"]
        return f"movieagent/v1/tasks/{owner}/{sid}/images/{iid}"

    def cache_image(self, image_id, data):
        self.store.storage.put(self.image_key(image_id), data)

    def get_image(self, task_id, image_id):
        return self.store.storage.get(self.image_key(task_id + "." + image_id))[0]

    def get_images(self, task_id, with_blobs=True):
        with self.store._lock:
            rows = [dict(r) for r in self.store._sessions[task_id]["doc"]["images"]]
        if with_blobs:
            for row in rows:
                row["image_blob"] = self.store.storage.get(self.image_key(row["id"]))[0]
        return rows
