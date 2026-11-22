"""Generation jobs against PostgreSQL with the stand-in worker: start, make a song, fetch it, stop."""
import time

import pytest

from generationstation.generation import GenerationManager
from generationstation.lifecycle import LifecycleError, LifecycleManager
from generationstation.process_worker import ProcessSupervisor
from tests.runtime_fixtures import free_port, host
from tests.test_generation import yue2_catalog
from tests.test_runtime_lifecycle_postgres import migrated_store, settings, wait_for

pytestmark = pytest.mark.database


def wait_job(generation, job_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = generation.get(job_id)
        if job["status"] in {"done", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job stayed {job['status']}")


def test_make_a_song_and_fetch_the_file(tmp_path):
    port = free_port()
    with migrated_store() as store:
        catalog = yue2_catalog(port, tmp_path / "out")
        lifecycle = LifecycleManager(store, settings(), catalog=catalog,
                                     runtime_adapter=ProcessSupervisor(tmp_path / "runtime", poll_seconds=0.1))
        lifecycle.sync_catalog()
        generation = GenerationManager(store, catalog)
        try:
            with pytest.raises(LifecycleError) as not_ready:
                generation.create("yue2", {"style": "pop", "lyrics": "la"})
            assert not_ready.value.code == "MODEL_NOT_READY"

            # 4080 is index 1 here: 14 GiB free needed, 14 available after zero headroom.
            started = lifecycle.create_runtime_load("yue2", None, {}, [1], "key-yue2-start", host((30, 14)))
            assert wait_for(lifecycle, started["id"], {"ready", "failed"})["status"] == "ready"

            with pytest.raises(LifecycleError) as invalid:
                generation.create("yue2", {"lyrics": "la"})
            assert invalid.value.code == "INPUTS_INVALID" and "Style is required" in invalid.value.message

            job = generation.create("yue2", {"style": "indie pop", "lyrics": "[Verse]\nla la", "seed": 11})
            assert job["status"] == "queued" and job["inputs"]["mode"] == "full"
            done = wait_job(generation, job["id"])
            assert done["status"] == "done", done
            assert done["outputs"][0]["name"] == "song.wav" and done["progress"] == "Done: seed 11"
            assert done["details"]["seed"] == 11 and done["details"]["seconds"] > 0
            assert done["launch"] == {"preset": "songs", "settings": done["launch"]["settings"], "gpus": [1]}
            path, mime = generation.output_path(job["id"], "song.wav")
            assert mime == "audio/wav" and path.read_bytes()[:4] == b"RIFF"
            for bad in ("../runtimes.json", "melody.abc"):
                with pytest.raises(LifecycleError):
                    generation.output_path(job["id"], bad)

            failing = generation.create("yue2", {"style": "fail", "lyrics": "x"})
            failed = wait_job(generation, failing["id"])
            assert failed["status"] == "failed" and "could not be planned" in failed["error_message"]
            assert [j["id"] for j in generation.list("yue2")["jobs"]] == [failing["id"], job["id"]]

            stopped_early = generation.create("yue2", {"style": "slow", "lyrics": "x"})
            waiting = generation.create("yue2", {"style": "pop", "lyrics": "x"})
            assert generation.cancel(waiting["id"])["status"] == "cancelled"
            assert generation.cancel(stopped_early["id"])["status"] in {"running", "cancelled", "queued"}
            assert wait_job(generation, stopped_early["id"])["status"] == "cancelled"
            with pytest.raises(LifecycleError) as finished:
                generation.cancel(stopped_early["id"])
            assert finished.value.code == "JOB_FINISHED"
            assert generation.delete(waiting["id"])["deleted"]

            slow = generation.create("yue2", {"style": "slow", "lyrics": "x"})
            with pytest.raises(LifecycleError) as running:
                generation.delete(slow["id"])
            assert running.value.code == "JOB_RUNNING"
            assert wait_job(generation, slow["id"])["status"] == "done"
            folder = tmp_path / "out" / slow["id"]
            assert (folder / "job.json").is_file()
            assert generation.delete(slow["id"]) == {"id": slow["id"], "deleted": True}
            assert not folder.exists() and slow["id"] not in [j["id"] for j in generation.list("yue2")["jobs"]]
            with pytest.raises(LifecycleError) as gone:
                generation.delete(slow["id"])
            assert gone.value.code == "JOB_NOT_FOUND"

            stop = lifecycle.create_unload("yue2", "key-yue2-stop")
            assert wait_for(lifecycle, stop["id"], {"unloaded", "cleanup_failed"})["status"] == "unloaded"
            with pytest.raises(LifecycleError) as stopped:
                generation.create("yue2", {"style": "pop", "lyrics": "la"})
            assert stopped.value.code == "MODEL_NOT_READY"
            # Finished files stay available after the model stops.
            assert generation.output_path(job["id"], "song.wav")[0].is_file()
        finally:
            lifecycle.shutdown()
