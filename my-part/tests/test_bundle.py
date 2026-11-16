import json

import numpy as np
import pandas as pd
import pytest
import torch

from ptop.bundle import MODEL_NAMES, REQUIRED_CONTRACTS, create_model, load_bundle, save_bundle
from ptop.preprocessing import FrozenPreprocessor
from ptop.schema import FEATURES, ContractError


@pytest.fixture
def processor():
    index = pd.MultiIndex.from_product([pd.date_range("2024-01-02 10:00", periods=6, freq="min"), [1]],
                                      names=["datetime", "instrument"])
    values = pd.DataFrame(np.arange(150, dtype=np.float64).reshape(6, 25), index=index, columns=FEATURES)
    return FrozenPreprocessor("N1").fit(values, values.notna(), referenced_rows=index,
                                        fit_start="2024-01-02", fit_end="2024-01-02").freeze(
                                            scale_review="synthetic fixture")


def save(path, model, processor, name="R1"):
    save_bundle(path, model, processor, model_name=name, window_length=6,
                contracts={key: "synthetic-fixture-v1" for key in REQUIRED_CONTRACTS},
                seed=17, training_record={"kind": "synthetic test"}, instrument_map={1: "SYNTHETIC"})


@pytest.mark.parametrize("name", MODEL_NAMES)
def test_json_preserves_all_model_parameters_and_bn_buffers(tmp_path, processor, name):
    torch.set_num_threads(1)
    model = create_model(name).eval()
    path = tmp_path / "bundle"
    save(path, model, processor, name)
    restored, recovered, manifest = load_bundle(path)
    assert {item.suffix for item in path.iterdir()} == {".json"}
    assert recovered.fingerprint == processor.fingerprint
    assert manifest["instrument_map"] == [[1, "SYNTHETIC"]]
    for key, tensor in model.state_dict().items():
        assert torch.equal(tensor, restored.state_dict()[key])
        assert tensor.dtype == restored.state_dict()[key].dtype
    inputs = (torch.randn(2, 6, 25), torch.ones(2, 6, 25, dtype=torch.bool), torch.ones(2, 6, dtype=torch.bool))
    with torch.no_grad():
        torch.testing.assert_close(model(*inputs), restored(*inputs), atol=1e-6, rtol=1e-5)


def test_rejects_dtype_mismatch_before_writing(tmp_path, processor):
    with pytest.raises(ContractError, match="类型"):
        save(tmp_path / "invalid", create_model("R1").double(), processor)
    assert not (tmp_path / "invalid").exists()


def test_rejects_negative_batchnorm_variance(tmp_path, processor):
    model = create_model("Net64")
    buffer = next(value for name, value in model.named_buffers() if name.endswith("running_var"))
    buffer.fill_(-1)
    with pytest.raises(ContractError, match="非负"):
        save(tmp_path / "invalid", model, processor, "Net64")
    assert not (tmp_path / "invalid").exists()


def test_detects_corrupted_model_and_missing_config(tmp_path, processor):
    path = tmp_path / "bundle"
    save(path, create_model("R1"), processor)
    weights = path / "model.json"
    weights.write_text("{}", encoding="utf-8")
    with pytest.raises(ContractError, match="校验"):
        load_bundle(path)
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["window_length"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ContractError, match="配置"):
        load_bundle(path)
