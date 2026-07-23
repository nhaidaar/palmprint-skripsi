import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import app.palm_processor as palm_processor_module
from app.palm_processor import PalmProcessor


@pytest.fixture
def processor(monkeypatch):
    load_model = PalmProcessor._load_model
    monkeypatch.setattr(PalmProcessor, "_load_hand_model", lambda self, path: None)
    monkeypatch.setattr(PalmProcessor, "_load_model", lambda self, path: None)
    instance = PalmProcessor()
    instance._load_model = load_model.__get__(instance, PalmProcessor)
    yield instance
    instance.close()


def test_extract_palm_roi_no_hand(processor):
    black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = processor.extract_palm_roi(black_frame)
    assert result is None


def test_apply_clahe(processor):
    gray_img = np.random.randint(0, 256, (100, 100), dtype=np.uint8)
    enhanced = processor.apply_clahe(gray_img)
    assert enhanced.shape == (100, 100)
    assert enhanced.dtype == np.uint8


def test_preprocess_roi_applies_gaussian_blur_before_clahe(processor):
    roi = np.zeros((32, 32, 3), dtype=np.uint8)
    roi[::2, ::2] = 255
    roi[1::2, 1::2] = 255

    gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(blurred)
    expected = cv2.resize(
        cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB),
        (224, 224),
        interpolation=cv2.INTER_CUBIC,
    ).astype(np.float32)

    processed = processor.preprocess_roi(roi)

    np.testing.assert_array_equal(processed, expected)


def test_palm_processor_has_no_notebook_preprocessor_state(processor):
    assert not hasattr(processor, "notebook_preprocessor")
    assert not hasattr(processor, "warmup_notebook_preprocessor")


def test_extract_embedding_from_frame_returns_none_tuple_when_no_roi(processor, monkeypatch):
    monkeypatch.setattr(processor, "extract_palm_roi", lambda frame: None)

    result = processor.extract_embedding_from_frame(np.zeros((10, 10, 3), dtype=np.uint8))

    assert result == (None, None)


def test_extract_embedding_from_frame_returns_embedding_and_model_input(processor, monkeypatch):
    roi = np.full((20, 20, 3), 10, dtype=np.uint8)
    model_input = np.full((224, 224, 3), 20, dtype=np.float32)
    embedding = np.ones(128, dtype=np.float32)
    monkeypatch.setattr(processor, "extract_palm_roi", lambda frame: roi)
    monkeypatch.setattr(processor, "preprocess_roi", lambda value: model_input)
    monkeypatch.setattr(processor, "_infer_embedding", lambda value: embedding)

    result = processor.extract_embedding_from_frame(np.zeros((30, 30, 3), dtype=np.uint8))

    assert result[0] is embedding
    assert result[1] is model_input


def test_extract_embedding_from_roi_returns_none_tuple_for_empty_roi(processor):
    empty_roi = np.empty((0, 0, 3), dtype=np.uint8)

    assert processor.extract_embedding_from_roi(empty_roi) == (None, None)


def test_extract_embedding_from_roi_preprocesses_without_client_rotation(processor, monkeypatch):
    roi = np.full((20, 20, 3), 10, dtype=np.uint8)
    model_input = np.full((224, 224, 3), 20, dtype=np.float32)
    embedding = np.ones(128, dtype=np.float32)
    seen = {}

    def fake_preprocess(value):
        seen["roi"] = value
        return model_input

    monkeypatch.setattr(processor, "preprocess_roi", fake_preprocess)
    monkeypatch.setattr(processor, "_infer_embedding", lambda value: embedding)

    result = processor.extract_embedding_from_roi(roi)

    assert seen["roi"] is roi
    assert result == (embedding, model_input)


def test_extract_embedding_from_roi_serializes_tta_transactions(processor, monkeypatch):
    first_invoke = threading.Event()
    release_first = threading.Event()
    second_attempted = threading.Event()
    second_invoked = threading.Event()
    invoke_markers = []
    marker_lock = threading.Lock()

    class CoordinatedInterpreter:
        def __init__(self):
            self.marker = 0

        def set_tensor(self, index, value):
            self.marker = int(np.max(value))

        def invoke(self):
            with marker_lock:
                invoke_markers.append(self.marker)
                invoke_number = len(invoke_markers)
            if self.marker == 2:
                second_invoked.set()
            if invoke_number == 1:
                first_invoke.set()
                release_first.wait(timeout=1.0)

        def get_tensor(self, index):
            return np.full((1, 128), float(self.marker), dtype=np.float32)

    def fake_preprocess(roi):
        return np.full((224, 224, 3), float(roi[0, 0, 0]), dtype=np.float32)

    def run_second():
        second_attempted.set()
        return processor.extract_embedding_from_roi(
            np.full((20, 20, 3), 2, dtype=np.uint8)
        )

    processor.interpreter = CoordinatedInterpreter()
    processor._input_index = 1
    processor._output_index = 2
    monkeypatch.setattr(processor, "preprocess_roi", fake_preprocess)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            processor.extract_embedding_from_roi,
            np.full((20, 20, 3), 1, dtype=np.uint8),
        )
        assert first_invoke.wait(timeout=1.0)
        second = executor.submit(run_second)
        assert second_attempted.wait(timeout=1.0)
        interleaved = second_invoked.wait(timeout=0.2)
        release_first.set()
        first.result(timeout=1.0)
        second.result(timeout=1.0)

    assert interleaved is False
    assert invoke_markers == [1, 1, 1, 2, 2, 2]


def test_extract_palm_roi_serializes_landmarker_detection(processor):
    first_detect = threading.Event()
    release_first = threading.Event()
    second_attempted = threading.Event()
    second_detected = threading.Event()
    call_count = 0
    call_count_lock = threading.Lock()

    class CoordinatedLandmarker:
        def detect(self, image):
            nonlocal call_count
            with call_count_lock:
                call_count += 1
                call_number = call_count
            if call_number == 1:
                first_detect.set()
                release_first.wait(timeout=1.0)
            else:
                second_detected.set()
            return SimpleNamespace(hand_landmarks=[])

        def close(self):
            pass

    frame = np.full((20, 20, 3), 100, dtype=np.uint8)
    processor._hand_landmarker = CoordinatedLandmarker()

    def run_second():
        second_attempted.set()
        return processor.extract_palm_roi(frame)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(processor.extract_palm_roi, frame)
        assert first_detect.wait(timeout=1.0)
        second = executor.submit(run_second)
        assert second_attempted.wait(timeout=1.0)
        interleaved = second_detected.wait(timeout=0.2)
        release_first.set()
        assert first.result(timeout=1.0) is None
        assert second.result(timeout=1.0) is None

    assert interleaved is False


def test_infer_embedding_runs_three_rotations_and_normalizes(processor, monkeypatch):
    model_input = np.zeros((224, 224, 3), dtype=np.float32)
    angles = []
    outputs = [
        3.0 * np.eye(1, 128, 0, dtype=np.float32).reshape(128),
        4.0 * np.eye(1, 128, 1, dtype=np.float32).reshape(128),
        5.0 * np.eye(1, 128, 2, dtype=np.float32).reshape(128),
    ]

    class FakeInterpreter:
        def __init__(self):
            self.invoke_count = 0

        def set_tensor(self, index, value):
            assert index == 1
            assert value.shape == (1, 224, 224, 3)

        def invoke(self):
            self.invoke_count += 1

        def get_tensor(self, index):
            assert index == 2
            return outputs[self.invoke_count - 1][None, :]

    def fake_rotate(value, angle):
        angles.append(angle)
        return value

    processor.interpreter = FakeInterpreter()
    processor._input_index = 1
    processor._output_index = 2
    monkeypatch.setattr(processor, "_rotate_model_input", fake_rotate)

    result = processor._infer_embedding(model_input)
    normalized_outputs = [processor._normalize_embedding(output) for output in outputs]
    expected = processor._normalize_embedding(np.mean(normalized_outputs, axis=0))

    assert angles == [0.0, -6.0, 6.0]
    assert processor.interpreter.invoke_count == 3
    assert result == pytest.approx(expected)
    assert np.linalg.norm(result) == pytest.approx(1.0)


def test_rotate_model_input_applies_expected_affine_transforms(processor):
    model_input = np.zeros((9, 9, 3), dtype=np.float32)
    model_input[1, 2] = (10.0, 20.0, 30.0)

    assert processor._rotate_model_input(model_input, 0.0) is model_input

    for angle in (-6.0, 6.0):
        matrix = cv2.getRotationMatrix2D((4.5, 4.5), angle, 1.0)
        expected = cv2.warpAffine(
            model_input,
            matrix,
            (9, 9),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        ).astype(np.float32)
        rotated = processor._rotate_model_input(model_input, angle)

        np.testing.assert_array_equal(rotated, expected)
        assert not np.array_equal(rotated, model_input)


@pytest.mark.parametrize("output_size", (127, 129))
def test_infer_embedding_rejects_non_128_output(processor, output_size):
    class FakeInterpreter:
        def set_tensor(self, index, value):
            pass

        def invoke(self):
            pass

        def get_tensor(self, index):
            return np.ones((1, output_size), dtype=np.float32)

    processor.interpreter = FakeInterpreter()
    processor._input_index = 1
    processor._output_index = 2

    with pytest.raises(ValueError, match="128"):
        processor._infer_embedding(np.zeros((224, 224, 3), dtype=np.float32))


@pytest.mark.parametrize(
    "output",
    (
        np.zeros(128, dtype=np.float32),
        np.full(128, np.nan, dtype=np.float32),
        np.full(128, np.inf, dtype=np.float32),
    ),
)
def test_infer_embedding_rejects_invalid_model_output(processor, output):
    class FakeInterpreter:
        def set_tensor(self, index, value):
            pass

        def invoke(self):
            pass

        def get_tensor(self, index):
            return output[None, :]

    processor.interpreter = FakeInterpreter()
    processor._input_index = 1
    processor._output_index = 2

    with pytest.raises(ValueError, match="finite non-zero"):
        processor._infer_embedding(np.zeros((224, 224, 3), dtype=np.float32))


def test_old_embedding_api_is_removed(processor):
    retired_names = (
        "get_embedding_with_processed_roi",
        "get_embedding",
        "get_embedding_from_notebook_frame",
        "get_embedding_from_roi_with_processed_roi",
        "get_embedding_from_roi",
        "_run_inference_with_optional_tta",
        "_run_inference",
    )
    for name in retired_names:
        assert not hasattr(processor, name)


def fake_landmarks(points):
    landmarks = [SimpleNamespace(x=0.5, y=0.5) for _ in range(21)]
    for index, point in points.items():
        landmarks[index] = SimpleNamespace(x=point[0], y=point[1])
    return landmarks


def test_registration_guidance_metrics_reports_no_hand(processor):
    class FakeLandmarker:
        def close(self):
            pass

        def detect(self, image):
            return SimpleNamespace(hand_landmarks=[])

    processor._hand_landmarker = FakeLandmarker()

    metrics = processor.get_registration_guidance_metrics(
        np.full((100, 200, 3), 120, dtype=np.uint8),
        previous_metrics=None,
    )

    assert metrics["hand_detected"] is False
    assert metrics["hand_clipped"] is True
    assert metrics["steady"] is False


def test_registration_guidance_metrics_uses_mediapipe_landmarks(processor):
    class FakeLandmarker:
        def close(self):
            pass

        def detect(self, image):
            return SimpleNamespace(hand_landmarks=[fake_landmarks({
                0: (0.50, 0.80),
                5: (0.35, 0.45),
                9: (0.50, 0.42),
                17: (0.65, 0.45),
            })])

    processor._hand_landmarker = FakeLandmarker()

    metrics = processor.get_registration_guidance_metrics(
        np.full((100, 200, 3), 120, dtype=np.uint8),
        previous_metrics={
            "hand_detected": True,
            "height_ratio": 0.38,
            "rotation_degrees": 0.0,
            "center_x_ratio": 0.50,
        },
    )

    assert metrics["hand_detected"] is True
    assert metrics["hand_clipped"] is False
    assert metrics["height_ratio"] > 0
    assert 0.45 <= metrics["center_x_ratio"] <= 0.55
    assert abs(metrics["rotation_degrees"]) < 1.0
    assert metrics["brightness"] == 120.0
    assert "blur_score" in metrics
    assert metrics["steady"] is True


def test_registration_guidance_metrics_detects_clipped_hand(processor):
    class FakeLandmarker:
        def close(self):
            pass

        def detect(self, image):
            return SimpleNamespace(hand_landmarks=[fake_landmarks({
                0: (0.01, 0.80),
                5: (0.35, 0.45),
                9: (0.50, 0.42),
                17: (0.65, 0.45),
            })])

    processor._hand_landmarker = FakeLandmarker()

    metrics = processor.get_registration_guidance_metrics(
        np.full((100, 200, 3), 120, dtype=np.uint8),
        previous_metrics=None,
    )

    assert metrics["hand_clipped"] is True


def test_extract_palm_roi_rejects_small_palm_width(processor):
    class FakeLandmarker:
        def close(self):
            pass

        def detect(self, image):
            return SimpleNamespace(hand_landmarks=[fake_landmarks({
                0: (0.50, 0.80),
                5: (0.50, 0.45),
                9: (0.50, 0.42),
                17: (0.51, 0.45),
            })])

    processor._hand_landmarker = FakeLandmarker()

    result = processor.extract_palm_roi(np.full((100, 100, 3), 120, dtype=np.uint8))

    assert result is None


def test_extract_palm_roi_normalizes_opposite_hand_rotation(processor, monkeypatch):
    class FakeLandmarker:
        def close(self):
            pass

        def detect(self, image):
            return SimpleNamespace(hand_landmarks=[fake_landmarks({
                0: (0.50, 0.80),
                5: (0.65, 0.45),
                9: (0.50, 0.42),
                17: (0.35, 0.45),
            })])

    angles = []

    def fake_rotation_matrix(center, angle, scale):
        angles.append(angle)
        return np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)

    processor._hand_landmarker = FakeLandmarker()
    monkeypatch.setattr(palm_processor_module.cv2, "getRotationMatrix2D", fake_rotation_matrix)

    roi = processor.extract_palm_roi(np.full((100, 200, 3), 120, dtype=np.uint8))

    assert roi is not None
    assert angles == [0.0]


def test_compute_similarity_skips_incompatible_embedding_dimensions(processor):
    result = processor.compute_similarity(
        np.ones(128, dtype=np.float32),
        [{"id": 1, "name": "Old", "embedding": np.ones(1280, dtype=np.float32)}],
        threshold=0.7,
    )

    assert result["status"] == "DENIED"
    assert result["closest_match"] is None
    assert result["similarity"] == 0.0


def test_compute_similarity_matches_compatible_template(processor):
    result = processor.compute_similarity(
        np.array([1.0, 0.0], dtype=np.float32),
        [
            {"id": 1, "name": "Alice", "embedding": np.array([1.0, 0.0], dtype=np.float32), "hand": "left"},
            {"id": 2, "name": "Bob", "embedding": np.array([0.0, 1.0], dtype=np.float32), "hand": "right"},
        ],
        threshold=0.7,
    )

    assert result["status"] == "ALLOWED"
    assert result["name"] == "Alice"
    assert result["user_id"] == 1
    assert result["similarity"] == 1.0


def test_compute_similarity_allows_score_equal_to_threshold(processor):
    result = processor.compute_similarity(
        np.array([1.0, 0.0], dtype=np.float32),
        [{"id": 1, "name": "Alice", "embedding": np.array([1.0, 0.0], dtype=np.float32)}],
        threshold=1.0,
    )

    assert result["status"] == "ALLOWED"
    assert result["similarity"] == 1.0


def test_model_path_is_repository_root():
    from app.palm_processor import MODEL_PATH

    assert MODEL_PATH == Path(__file__).resolve().parent.parent / "model.tflite"


def test_missing_model_raises_file_not_found(processor, tmp_path):
    missing_path = tmp_path / "missing.tflite"

    with pytest.raises(FileNotFoundError, match="missing.tflite"):
        processor._load_model(missing_path)


def test_model_directory_raises_file_not_found(processor, tmp_path):
    with pytest.raises(FileNotFoundError, match=str(tmp_path).replace("\\", "\\\\")):
        processor._load_model(tmp_path)


def install_fake_tflite_module(monkeypatch, interpreter_class):
    package = types.ModuleType("tflite_runtime")
    package.__path__ = []
    module = types.ModuleType("tflite_runtime.interpreter")
    module.Interpreter = interpreter_class
    monkeypatch.setitem(sys.modules, "tflite_runtime", package)
    monkeypatch.setitem(sys.modules, "tflite_runtime.interpreter", module)


def test_interpreter_load_failure_is_wrapped(processor, monkeypatch, tmp_path):
    model_path = tmp_path / "model.tflite"
    model_path.write_bytes(b"test")
    sentinel = OSError("backend failed")

    class BrokenInterpreter:
        def __init__(self, model_path, num_threads=None):
            raise sentinel

    install_fake_tflite_module(monkeypatch, BrokenInterpreter)

    with pytest.raises(RuntimeError, match="Unable to load TFLite model") as exc_info:
        processor._load_model(model_path)

    assert exc_info.value.__cause__ is sentinel


def test_model_loader_requests_four_threads(processor, monkeypatch, tmp_path):
    model_path = tmp_path / "model.tflite"
    model_path.write_bytes(b"test")
    thread_values = []

    class ThreadedInterpreter:
        def __init__(self, model_path, num_threads=None):
            thread_values.append(num_threads)

        def allocate_tensors(self):
            pass

        def get_input_details(self):
            return [{"index": 1, "shape": np.array([1, 224, 224, 3]), "dtype": np.float32}]

        def get_output_details(self):
            return [{"index": 2, "shape": np.array([1, 128]), "dtype": np.float32}]

    install_fake_tflite_module(monkeypatch, ThreadedInterpreter)

    processor._load_model(model_path)

    assert thread_values == [4]


def test_model_loader_retries_without_thread_argument(processor, monkeypatch, tmp_path):
    model_path = tmp_path / "model.tflite"
    model_path.write_bytes(b"test")
    thread_values = []

    class CompatibleInterpreter:
        def __init__(self, model_path, num_threads=None):
            thread_values.append(num_threads)
            if num_threads is not None:
                raise TypeError("num_threads unsupported")

        def allocate_tensors(self):
            pass

        def get_input_details(self):
            return [{"index": 1, "shape": np.array([1, 224, 224, 3]), "dtype": np.float32}]

        def get_output_details(self):
            return [{"index": 2, "shape": np.array([1, 128]), "dtype": np.float32}]

    install_fake_tflite_module(monkeypatch, CompatibleInterpreter)

    processor._load_model(model_path)

    assert thread_values == [4, None]


def test_model_output_metadata_rejects_non_128_shape(processor, monkeypatch, tmp_path):
    model_path = tmp_path / "model.tflite"
    model_path.write_bytes(b"test")

    class WrongOutputInterpreter:
        def __init__(self, model_path, num_threads=None):
            pass

        def allocate_tensors(self):
            pass

        def get_input_details(self):
            return [{"index": 1, "shape": np.array([1, 224, 224, 3]), "dtype": np.float32}]

        def get_output_details(self):
            return [{"index": 2, "shape": np.array([1, 127]), "dtype": np.float32}]

    install_fake_tflite_module(monkeypatch, WrongOutputInterpreter)

    with pytest.raises(ValueError, match="128"):
        processor._load_model(model_path)


@pytest.mark.parametrize(
    ("input_shape", "input_dtype", "output_dtype", "message"),
    (
        ((1, 128, 128, 3), np.float32, np.float32, "input shape"),
        ((1, 224, 224, 3), np.uint8, np.float32, "input dtype"),
        ((1, 224, 224, 3), np.float32, np.int8, "output dtype"),
    ),
)
def test_model_loader_validates_tensor_contract(
    processor,
    monkeypatch,
    tmp_path,
    input_shape,
    input_dtype,
    output_dtype,
    message,
):
    model_path = tmp_path / "model.tflite"
    model_path.write_bytes(b"test")

    class InvalidContractInterpreter:
        def __init__(self, model_path, num_threads=None):
            pass

        def allocate_tensors(self):
            pass

        def get_input_details(self):
            return [{"index": 1, "shape": np.array(input_shape), "dtype": input_dtype}]

        def get_output_details(self):
            return [{"index": 2, "shape": np.array([1, 128]), "dtype": output_dtype}]

    install_fake_tflite_module(monkeypatch, InvalidContractInterpreter)

    with pytest.raises(ValueError, match=message):
        processor._load_model(model_path)
