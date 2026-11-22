import pytest

from tools.finops_calc import (
    calculate_llm_finops,
    calculate_system_capacity,
    estimate_gpu_vram,
)


def test_calculate_system_capacity_littles_law() -> None:
    res = calculate_system_capacity(
        rps=1000.0,
        avg_latency_ms=200.0,
        payload_kb=4.0,
        years=1.0,
        peak_multiplier=3.0,
    )
    # Peak = 3000 RPS * 0.2s = 600 concurrent slots
    assert res.peak_rps == 3000.0
    assert res.required_concurrency == 600.0
    assert res.storage_tb > 0.1
    assert res.egress_gb_per_month > 9000.0


def test_calculate_llm_finops_savings_math() -> None:
    res = calculate_llm_finops(
        monthly_queries=500_000,
        avg_input_tokens=1500,
        avg_output_tokens=400,
        price_per_1m_in=3.0,
        price_per_1m_out=15.0,
        cache_hit_rate=0.35,
        small_model_route_rate=0.45,
        small_model_discount=0.85,
    )
    assert res.baseline_monthly_usd == 5250.0
    assert res.optimized_monthly_usd < res.baseline_monthly_usd
    assert res.savings_pct > 55.0
    assert res.annual_savings_usd == round(res.monthly_savings_usd * 12.0, 2)


def test_estimate_gpu_vram_and_validation() -> None:
    res = estimate_gpu_vram(params_b=70.0, quant_bits=4, ctx_len=8192, concurrency=32)
    assert res.weights_gb == 35.0
    assert res.total_vram_gb > res.weights_gb
    assert res.recommended_h100_80gb_gpus >= 1

    with pytest.raises(ValueError):
        calculate_llm_finops(
            monthly_queries=100,
            avg_input_tokens=100,
            avg_output_tokens=100,
            price_per_1m_in=1.0,
            price_per_1m_out=2.0,
            cache_hit_rate=1.5,
        )
