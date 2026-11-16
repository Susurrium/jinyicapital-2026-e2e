import copy

import pytest
import torch
from ptop._vendor.qlib.models import Net
from torch import nn

from ptop.encoders import (
    ALSTMEncoder,
    DeepLOBEncoder,
    GroupedNetEncoder,
    PatchEncoder,
    RawEncoder,
    UnifiedNetEncoder,
    field_indices,
    predictable_mask,
)
from ptop.models import count_parameters
from ptop.schema import BOOK12_FIELDS, FEATURES, ContractError


@pytest.fixture(autouse=True)
def single_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    torch.manual_seed(17)
    yield
    torch.set_num_threads(previous)


def inputs(lengths=(7, 4, 1), width=9):
    valid = torch.arange(width).unsqueeze(0) >= width - torch.tensor(lengths).unsqueeze(1)
    observed = valid.unsqueeze(-1).expand(-1, -1, 25).clone()
    x = torch.randn(len(lengths), width, 25).masked_fill(~observed, 0)
    return x, observed, valid


@pytest.mark.parametrize(
    ("factory", "width", "parameters"),
    [
        (RawEncoder, 50, 0),
        (ALSTMEncoder, 64, 3264),
        (UnifiedNetEncoder, 64, 30016),
        (lambda: UnifiedNetEncoder(192), 192, 62912),
        (GroupedNetEncoder, 192, 64448),
        (lambda: PatchEncoder(1), 64, 3328),
        (lambda: PatchEncoder(5), 64, 16384),
        (DeepLOBEncoder, 192, 69344),
    ],
)
def test_encoder_shapes_parameter_counts_and_padding(factory, width, parameters):
    encoder = factory().eval()
    x, observed, valid = inputs()
    tokens, token_valid = encoder(x, observed, valid)
    assert tokens.shape[-1] == width
    assert token_valid.shape == tokens.shape[:2]
    assert tokens[~token_valid].eq(0).all()
    assert torch.isfinite(tokens).all()
    assert count_parameters(encoder) == parameters


def test_raw_field_and_observation_order():
    x, observed, valid = inputs((3,), 3)
    x[0, 0, 0] = 0
    observed[0, 1, 2] = False
    x[0, 1, 2] = 0
    tokens, _ = RawEncoder()(x, observed, valid)
    torch.testing.assert_close(tokens[..., :25], x)
    torch.testing.assert_close(tokens[..., 25:], observed.float())
    book, _ = RawEncoder(BOOK12_FIELDS)(x, observed, valid)
    expected = [FEATURES.index(f"{field}{level}") for level in (1, 2, 3) for field in ("ask_price", "ask_volume", "bid_price", "bid_volume")]
    torch.testing.assert_close(book[..., :12], x[..., expected])
    torch.testing.assert_close(book[..., 12:], observed[..., expected].float())


@pytest.mark.parametrize("factory", [RawEncoder, ALSTMEncoder, UnifiedNetEncoder, GroupedNetEncoder, PatchEncoder, DeepLOBEncoder])
def test_all_empty_windows_are_rejected(factory):
    x, observed, valid = inputs((3, 2), 3)
    observed[1] = False
    x[1] = 0
    with pytest.raises(ContractError, match="字段子集全空"):
        factory()(x, observed, valid)


def test_field_subset_predictable_requires_a_used_field():
    x, observed, valid = inputs((2,), 2)
    observed[:] = False
    observed[..., 0] = True
    x[~observed] = 0
    assert predictable_mask(observed).tolist() == [True]
    assert predictable_mask(observed, BOOK12_FIELDS).tolist() == [False]
    with pytest.raises(ContractError, match="字段子集全空"):
        DeepLOBEncoder()(x, observed, valid)


@pytest.mark.parametrize("case", ["dtype", "mask_dtype", "nonfinite", "outside", "dirty_missing", "interior_padding", "empty"])
def test_invalid_input_contract(case):
    x, observed, valid = inputs((2,), 3)
    if case == "dtype":
        x = x.double()
    elif case == "mask_dtype":
        observed = observed.float()
    elif case == "nonfinite":
        x[0, 1, 0] = torch.inf
    elif case == "outside":
        observed[0, 0, 0] = True
    elif case == "dirty_missing":
        x[0, 0, 0] = 1
    elif case == "interior_padding":
        valid[0] = torch.tensor([True, False, True])
        observed[0] = valid[0].unsqueeze(-1)
        x[~observed] = 0
    elif case == "empty":
        x, observed, valid = x[:, :0], observed[:, :0], valid[:, :0]
    with pytest.raises(ContractError):
        RawEncoder()(x, observed, valid)


@pytest.mark.parametrize("fields", [(), ("close", "close"), ("unknown",)])
def test_invalid_field_selection(fields):
    with pytest.raises(ContractError):
        field_indices(fields)


def test_unified_net_matches_official_forward_gradient_and_bn_state():
    encoder = UnifiedNetEncoder().train()
    source = copy.deepcopy(encoder.net)
    assert isinstance(source, Net)
    x, observed, valid = inputs()
    x.requires_grad_()
    source_x = x.detach().clone().requires_grad_()
    torch.manual_seed(101)
    tokens, _ = encoder(x, observed, valid)
    torch.manual_seed(101)
    rows = torch.cat((source_x, observed.float()), dim=-1)[valid]
    expected = source(rows)
    torch.testing.assert_close(tokens[valid], expected, atol=1e-6, rtol=1e-5)
    tokens.square().sum().backward()
    expected.square().sum().backward()
    torch.testing.assert_close(x.grad, source_x.grad, atol=1e-6, rtol=1e-5)
    for (name, parameter), (reference_name, reference) in zip(encoder.net.named_parameters(), source.named_parameters(), strict=True):
        assert name == reference_name
        torch.testing.assert_close(parameter.grad, reference.grad, atol=1e-6, rtol=1e-5)
    for name, value in source.state_dict().items():
        torch.testing.assert_close(encoder.net.state_dict()[name], value)


def test_grouped_net_uses_complete_book_group_and_source_group_order():
    encoder = GroupedNetEncoder().train()
    references = copy.deepcopy(encoder.nets)
    x, observed, valid = inputs((4, 2), 5)
    observed[0, :, :4] = False
    x[~observed] = 0
    torch.manual_seed(101)
    actual, _ = encoder(x, observed, valid)
    torch.manual_seed(101)
    expected = []
    for indices, reference in zip((tuple(range(4)), tuple(range(4, 7)), tuple(range(7, 25))), references, strict=True):
        assert isinstance(reference, Net)
        values = torch.cat((x[..., indices], observed[..., indices].float()), dim=-1)
        expected.append(reference(values[valid]))
    torch.testing.assert_close(actual[valid], torch.cat(expected, dim=-1), atol=1e-6, rtol=1e-5)
    for left, right in zip(encoder.nets, references, strict=True):
        for name, value in right.state_dict().items():
            torch.testing.assert_close(left.state_dict()[name], value)


@pytest.mark.parametrize("factory", [UnifiedNetEncoder, GroupedNetEncoder])
def test_bn_ignores_structural_padding_but_keeps_missing_minutes(factory):
    encoder = factory().train()
    twin = copy.deepcopy(encoder)
    x, observed, valid = inputs((4, 4), 4)
    observed[:, 1] = False
    x[:, 1] = 0
    padded_x = torch.nn.functional.pad(x, (0, 0, 5, 0))
    padded_observed = torch.nn.functional.pad(observed, (0, 0, 5, 0))
    padded_valid = torch.nn.functional.pad(valid, (5, 0))
    torch.manual_seed(43)
    compact, _ = encoder(x, observed, valid)
    torch.manual_seed(43)
    padded, _ = twin(padded_x, padded_observed, padded_valid)
    torch.testing.assert_close(padded[:, 5:], compact)
    for name, value in encoder.state_dict().items():
        torch.testing.assert_close(twin.state_dict()[name], value)
    for module in encoder.modules():
        if isinstance(module, nn.BatchNorm1d):
            assert module.num_batches_tracked.item() == 1


@pytest.mark.parametrize("factory", [UnifiedNetEncoder, GroupedNetEncoder])
def test_bn_insufficient_rows_fail_before_state_mutation(factory):
    encoder = factory().train()
    before = copy.deepcopy(encoder.state_dict())
    with pytest.raises(ContractError, match="至少需要两个"):
        encoder(*inputs((1,), 3))
    for name, value in encoder.state_dict().items():
        torch.testing.assert_close(value, before[name])


@pytest.mark.parametrize("factory", [UnifiedNetEncoder, GroupedNetEncoder])
def test_bn_eval_restores_buffers_and_is_batch_invariant(factory):
    encoder = factory().train()
    batch = inputs()
    encoder(*batch)
    restored = factory().eval()
    restored.load_state_dict(encoder.state_dict(), strict=True)
    encoder.eval()
    before = copy.deepcopy(restored.state_dict())
    expected = encoder(*batch)[0]
    torch.testing.assert_close(restored(*batch)[0], expected)
    permutation = torch.tensor([2, 0, 1])
    actual = restored(*(v[permutation] for v in batch))[0]
    torch.testing.assert_close(actual[permutation.argsort()], expected, atol=1e-6, rtol=1e-5)
    for index in range(3):
        single = restored(*(v[index : index + 1] for v in batch))[0]
        torch.testing.assert_close(single, expected[index : index + 1], atol=1e-6, rtol=1e-5)
    for name, value in restored.state_dict().items():
        torch.testing.assert_close(value, before[name])


@pytest.mark.parametrize("patch_size", [1, 5])
def test_patch_field_first_flatten_endpoint_masks_and_bounds(patch_size):
    encoder = PatchEncoder(patch_size)
    x, observed, valid = inputs((7, 1), 7)
    x[0] = torch.arange(175, dtype=torch.float32).reshape(7, 25)
    observed[0, 3] = False
    x[0, 3] = 0
    patches, flags = encoder.patch_inputs(x, observed, valid)
    joined = torch.cat((x, observed.float(), valid.unsqueeze(-1).float()), dim=-1)
    count = (7 + patch_size - 1) // patch_size
    expected = torch.zeros(2, count, 51 * patch_size)
    for block in range(count):
        end = 7 - (count - block - 1) * patch_size
        start = max(0, end - patch_size)
        values = torch.nn.functional.pad(joined[:, start:end], (0, 0, patch_size - (end - start), 0))
        expected[:, block] = values.transpose(1, 2).flatten(1)
    torch.testing.assert_close(patches, expected)
    tokens, returned_flags = encoder(x, observed, valid)
    torch.testing.assert_close(returned_flags, flags)
    torch.testing.assert_close(tokens[flags], encoder.projection(expected)[flags])
    assert flags[0].all()
    assert flags[1].sum() == 1
    starts, ends = encoder.slot_bounds(valid)
    if patch_size == 5:
        assert starts.tolist() == [[0, 2], [-1, 6]]
        assert ends.tolist() == [[1, 6], [-1, 6]]
    else:
        assert starts[0].tolist() == list(range(7))
        assert ends[1].tolist() == [-1] * 6 + [6]


def test_patch_pure_padding_blocks_are_excluded():
    encoder = PatchEncoder(5)
    tokens, valid = encoder(*inputs((1,), 120))
    assert tokens.shape == (1, 24, 64)
    assert valid.tolist() == [[False] * 23 + [True]]
    assert tokens[:, :23].eq(0).all()


def test_deeplob_spatial_width_time_padding_pooling_and_initialization():
    encoder = DeepLOBEncoder().eval()
    book = torch.randn(2, 2, 3, 12)
    widths = []
    for block in encoder.blocks:
        book = block(book)
        widths.append(book.shape[-1])
        assert book.shape[2] == 3
    assert widths == [6, 3, 1]
    time_layer = encoder.blocks[0][1]
    assert time_layer[0].padding == (0, 0, 1, 2)
    with torch.no_grad():
        time_layer[1].weight.fill_(1)
        time_layer[1].bias.zero_()
    sequence = torch.arange(1, 4, dtype=torch.float32).reshape(1, 1, 3, 1).expand(1, 32, 3, 1)
    result = time_layer(sequence)
    torch.testing.assert_close(result[0, 0, :, 0], torch.tensor([192.0, 192.0, 160.0]))
    pool = encoder.branches[2][0]
    negatives = torch.tensor([-8.0, -7.0, -9.0]).reshape(1, 1, 3, 1)
    torch.testing.assert_close(pool(negatives).flatten(), torch.tensor([-7.0, -7.0, -7.0]))
    one = torch.tensor([-5.0]).reshape(1, 1, 1, 1)
    torch.testing.assert_close(pool(one), one)
    fresh = DeepLOBEncoder()
    assert not any(isinstance(layer, nn.BatchNorm2d) for layer in fresh.modules())
    for module in fresh.modules():
        if isinstance(module, nn.Conv2d):
            assert module.bias.eq(0).all()
            fan_in, fan_out = nn.init._calculate_fan_in_and_fan_out(module.weight)
            assert module.weight.abs().max() <= (6 / (fan_in + fan_out)) ** 0.5


def test_deeplob_length_grouping_and_dropout():
    encoder = DeepLOBEncoder().eval()
    batch = inputs((1, 5, 3, 5), 8)
    actual, flags = encoder(*batch)
    for i, length in enumerate((1, 5, 3, 5)):
        single = tuple(v[i : i + 1, -length:] for v in batch)
        expected, _ = encoder(*single)
        torch.testing.assert_close(actual[i : i + 1, -length:], expected, atol=1e-6, rtol=1e-5)
    assert torch.equal(flags, batch[2])
    torch.testing.assert_close(encoder(*batch)[0], actual, rtol=0, atol=0)
    encoder.train()
    ones = torch.ones(8, 192, 7)
    dropped = encoder.dropout(ones)
    assert dropped.eq(0).any()
    assert dropped.ne(0).any()
    torch.testing.assert_close(dropped, dropped[:, :, :1].expand_as(dropped))
