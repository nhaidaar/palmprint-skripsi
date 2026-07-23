import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import CAMERA_SOURCE, DEVICE_RUNTIME_ENABLED, DB_PATH
from app.database import Database
from app.device_runtime import build_device_runtime
from app.palm_processor import PalmProcessor
from app.routes import recognize, register, users, logs, debug, status, device_registration

log = logging.getLogger("palmgate")

db: Database = None
palm_processor: PalmProcessor = None
device_runtime = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, palm_processor, device_runtime
    active_error = None
    try:
        db = Database(DB_PATH)
        palm_processor = PalmProcessor()
        if DEVICE_RUNTIME_ENABLED and CAMERA_SOURCE == "usb":
            device_runtime = build_device_runtime(palm_processor, db)
            device_runtime.start()
        yield
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        cleanup_errors = []

        runtime = device_runtime
        device_runtime = None
        if runtime is not None:
            try:
                runtime.stop()
            except BaseException as exc:
                cleanup_errors.append(exc)
                log.exception("Failed to stop device runtime")

        processor = palm_processor
        palm_processor = None
        if processor is not None:
            try:
                processor.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
                log.exception("Failed to close palm processor")

        database = db
        db = None
        if database is not None:
            try:
                database.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
                log.exception("Failed to close database")

        if cleanup_errors and active_error is None:
            raise cleanup_errors[0]


app = FastAPI(title="Palmprint Recognition Preview", lifespan=lifespan)

app.include_router(recognize.router)
app.include_router(register.router)
app.include_router(users.router)
app.include_router(logs.router)
app.include_router(debug.router)
app.include_router(status.router)
app.include_router(device_registration.router)
