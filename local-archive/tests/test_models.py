import copy

import pytest
import torch
from ptop._vendor.qlib.models import ALSTMModel, GRUModel
from torch import nn

from ptop.encoders import GroupedNetEncoder, PatchEncoder, UnifiedNetEncoder
from ptop.models import AttentionModel, DeepLOBModel, R0Model, R1Model, count_parameters, load_keras_lstm_weights
from ptop.schema import BOOK12_FIELDS, FEATURES, ContractError


@pytest.fixture(autouse=True)
def single_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    torch.manual_seed(43)
    yield
    torch.set_num_threads(previous)


def inputs(lengths=(7, 4, 1), width=9):
    valid = torch.arange(width).unsqueeze(0) >= width - torch.tensor(lengths).unsqueeze(1)
    observed = valid.unsqueeze(-1).expand(-1, -1, 25).clone()
    x = torch.randn(len(lengths), width, 25).masked_fill(~observed, 0)
    return x, observed, valid


@pytest.mark.parametrize(("model_class", "source_class", "fields"), [(R0Model, GRUModel, FEATURES), (R1Model, ALSTMModel, FEATURES), (R1Model, ALSTMModel, BOOK12_FIELDS)])
@pytest.mark.parametrize("batch_size", [1, 3])
def test_embedded_model_full_window_forward_input_and_parameter_gradient_equivalence(model_class, source_class, fields, batch_size):
    torch.manual_seed(17)
    source = source_class(d_feat=2 * len(fields), hidden_size=64, num_layers=2, dropout=0.0)
    torch.manual_seed(17)
    adapted = model_class(fields=fields)
    x, observed, valid = inputs((8,) * batch_size, 8)
    x.requires_grad_()
    source_x = x.detach().clone().requires_grad_()
    selected = tuple(FEATURES.index(field) for field in fields)
    # Qlib 按字段、时间解释扁平输入，显式转置后再展平。
    flat = torch.cat((source_x[..., selected], observed[..., selected].float()), dim=-1).transpose(1, 2).contiguous().flatten(1)
    expected = source(flat).reshape(-1)
    actual = adapted(x, observed, valid)
    assert actual.shape == (batch_size,)
    torch.testing.assert_close(actual, expected, atol=1e-6, rtol=1e-5)
    weights = torch.arange(1, batch_size + 1).float()
    (actual * weights).sum().backward()
    (expected * weights).sum().backward()
    torch.testing.assert_close(x.grad, source_x.grad, atol=1e-6, rtol=1e-5)
    adapted_parameters = dict(adapted.named_parameters())
    for name, parameter in source.named_parameters():
        adapted_name = f"encoder.{name}" if name.startswith("net.") else name
        target = adapted_parameters[adapted_name]
        torch.testing.assert_close(target, parameter, rtol=0, atol=0)
        torch.testing.assert_close(target.grad, parameter.grad, atol=1e-6, rtol=1e-5)
    assert len(adapted_parameters) == len(dict(source.named_parameters()))


def test_reference_parameter_counts_and_source_module_ownership():
    r0, r1 = R0Model(), R1Model()
    assert count_parameters(r0) == 47297
    assert count_parameters(r1) == 55425
    assert count_parameters(r1.encoder) == 3264
    assert count_parameters(DeepLOBModel()) == 135457
    assert sum(isinstance(module, nn.GRU) for module in r1.modules()) == 1
    assert sum(isinstance(module, nn.Softmax) for module in r1.modules()) == 1


@pytest.mark.parametrize("factory", [R0Model, R1Model, DeepLOBModel, lambda: AttentionModel(PatchEncoder(5)), lambda: AttentionModel(GroupedNetEncoder())])
def test_variable_lengths_sample_order_and_batch_partitions(factory):
    model = factory().eval()
    batch = inputs((1, 7, 4, 7), 9)
    # 合法分钟全缺失仍保留位置。
    batch[1][1, 5] = False
    batch[0][1, 5] = 0
    before = copy.deepcopy(model.state_dict())
    expected = model(*batch)
    for i in range(4):
        single = tuple(v[i : i + 1] for v in batch)
        torch.testing.assert_close(model(*single), expected[i : i + 1], atol=1e-6, rtol=1e-5)
    permutation = torch.tensor([2, 0, 3, 1])
    actual = model(*(v[permutation] for v in batch))
    torch.testing.assert_close(actual[permutation.argsort()], expected, atol=1e-6, rtol=1e-5)
    for name, value in model.state_dict().items():
        torch.testing.assert_close(value, before[name])


@pytest.mark.parametrize("factory", [R0Model, R1Model, DeepLOBModel, lambda: AttentionModel(PatchEncoder(5))])
def test_left_padding_removal_matches_true_short_window(factory):
    model = factory().eval()
    batch = inputs((1, 7, 4), 9)
    expected = model(*batch)
    for i, length in enumerate((1, 7, 4)):
        short = tuple(v[i : i + 1, -length:] for v in batch)
        torch.testing.assert_close(model(*short), expected[i : i + 1], atol=1e-6, rtol=1e-5)


def test_attention_padding_weights_and_internal_missing_minutes():
    model = R1Model().eval()
    x, observed, valid = inputs((7, 3, 1), 9)
    observed[0, 4] = False
    x[0, 4] = 0
    scores, weights = model.forward_with_attention(x, observed, valid)
    assert scores.shape == (3,)
    assert weights[~valid].eq(0).all()
    torch.testing.assert_close(weights.sum(dim=1), torch.ones(3))
    assert weights[0, 4] > 0
    assert weights[2, -1] == 1
    with torch.no_grad():
        for parameter in model.att_net.parameters():
            parameter.zero_()
    _, equal = model.forward_with_attention(x, observed, valid)
    torch.testing.assert_close(equal[0, -7:], torch.full((7,), 1 / 7))


@pytest.mark.parametrize("factory", [R0Model, R1Model, DeepLOBModel, lambda: AttentionModel(UnifiedNetEncoder()), lambda: AttentionModel(UnifiedNetEncoder(192)), lambda: AttentionModel(GroupedNetEncoder()), lambda: AttentionModel(PatchEncoder(1)), lambda: AttentionModel(PatchEncoder(5))])
def test_joint_training_updates_all_modules_with_finite_gradients(factory):
    model = factory().train()
    batch = inputs((6, 4, 3), 8)
    batch[0].requires_grad_()
    before = {name: value.detach().clone() for name, value in model.named_parameters()}
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    optimizer.zero_grad()
    score = model(*batch)
    loss = nn.functional.mse_loss(score, torch.tensor([0.2, -0.1, 0.7]))
    loss.backward()
    for parameter in model.parameters():
        assert parameter.grad is not None
        assert torch.isfinite(parameter.grad).all()
    assert torch.isfinite(batch[0].grad).all()
    nn.utils.clip_grad_value_(model.parameters(), 3)
    optimizer.step()
    for name, module in model.named_children():
        parameters = list(module.named_parameters())
        if parameters:
            assert any(not torch.equal(parameter, before[f"{name}.{part}"]) for part, parameter in parameters)


@pytest.mark.parametrize("factory", [R0Model, R1Model, DeepLOBModel, lambda: AttentionModel(GroupedNetEncoder()), lambda: AttentionModel(PatchEncoder(5))])
def test_complete_model_state_reload(factory):
    model = factory().train()
    batch = inputs()
    model(*batch)
    model.eval()
    restored = factory().eval()
    restored.load_state_dict(model.state_dict(), strict=True)
    torch.testing.assert_close(restored(*batch), model(*batch), rtol=0, atol=0)
    broken = copy.deepcopy(model.state_dict())
    broken.pop(next(iter(broken)))
    with pytest.raises(RuntimeError, match="Missing key"):
        restored.load_state_dict(broken, strict=True)


@pytest.mark.parametrize("factory", [lambda: R1Model(BOOK12_FIELDS), DeepLOBModel])
def test_book_model_rejects_unused_only_observations(factory):
    x, observed, valid = inputs((3,), 3)
    observed[..., 4:] = False
    x[~observed] = 0
    with pytest.raises(ContractError, match="字段子集全空"):
        factory()(x, observed, valid)


def test_deeplob_lstm_initialization_matches_declared_keras_convention():
    model = DeepLOBModel()
    lstm = model.rnn
    expected = torch.zeros(256)
    expected[64:128] = 1
    torch.testing.assert_close(lstm.bias_ih_l0 + lstm.bias_hh_l0, expected)
    torch.testing.assert_close(lstm.weight_hh_l0.T @ lstm.weight_hh_l0, torch.eye(64), atol=1e-6, rtol=1e-5)
    assert lstm.weight_ih_l0.abs().max() <= (6 / (192 + 256)) ** 0.5
    assert model.fc_out.bias.eq(0).all()
    assert model.fc_out.weight.abs().max() <= (6 / 65) ** 0.5


def test_keras_gate_weight_transpose_and_combined_bias_mapping():
    lstm = nn.LSTM(3, 2, batch_first=True)
    kernel = torch.randn(3, 8)
    recurrent = torch.randn(2, 8)
    bias = torch.randn(8)
    load_keras_lstm_weights(lstm, kernel, recurrent, bias)
    x = torch.randn(2, 4, 3)
    h, c = torch.zeros(2, 2), torch.zeros(2, 2)
    expected = []
    # 直接按 Keras 文档声明的门语义核对跨框架参数映射。
    for minute in x.unbind(dim=1):
        i, f, candidate, o = (minute @ kernel + h @ recurrent + bias).chunk(4, dim=-1)
        c = f.sigmoid() * c + i.sigmoid() * candidate.tanh()
        h = o.sigmoid() * c.tanh()
        expected.append(h)
    actual, (last, cell) = lstm(x)
    torch.testing.assert_close(actual, torch.stack(expected, dim=1), atol=1e-6, rtol=1e-5)
    torch.testing.assert_close(last[0], h, atol=1e-6, rtol=1e-5)
    torch.testing.assert_close(cell[0], c, atol=1e-6, rtol=1e-5)
    before = copy.deepcopy(lstm.state_dict())
    with pytest.raises(ContractError):
        load_keras_lstm_weights(lstm, kernel, recurrent, torch.zeros(16))
    for name, value in lstm.state_dict().items():
        torch.testing.assert_close(value, before[name])
