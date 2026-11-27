# MCSync

## Commands (all from repo root)

Run the unit tests
```
python -m unittest discover -s tests -v
```

Run the integration tests
```
python -m unittest discover -v
```

Start the server with sync handling
```
python -m mcsync.cli start
```

Run checkpoint tests
```
python -m scripts.test_checkpoint -c 'main()'
```

Run a single unit test (examples)
```
python -m unittest tests.test_checkpoint.CheckpointTests.test_checkpoint_stops_snapshots_and_restarts -v
python -m unittest tests.test_snapshots.SnapshotTests.test_create_and_verify_snapshot -v
```

## What the snapshot should have

- mods
- world data
- run.bat
- eula.txt
- ops.json
- server.properties
- user_jvm_args.txt

## Open issues

- [ ] Snapshots aren't getting created
- [ ] Checkpoint unit tests don't call the actual snapshot creation functions. They only mock them (even though the actual function is imported)
