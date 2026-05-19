$env:PYTHONPATH = "$PWD;$PWD\\apps\\api"
uvicorn --app-dir apps/api gremlinboard_api.main:app --host 127.0.0.1 --port 8000 --no-access-log
