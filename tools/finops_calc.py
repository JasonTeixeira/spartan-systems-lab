"""
Spartan On-the-Job Capacity, GPU VRAM & Cloud/LLM FinOps Calculator.
Reusable CLI for back-of-the-envelope System Design, RFCs, and Executive Savings Proofs.

Examples:
  uv run python tools/finops_calc.py system --rps 2500 --avg-latency-ms 120 --payload-kb 2 --years 3
  uv run python tools/finops_calc.py llm --monthly-queries 500000 --avg-input-tokens 1500 \
      --avg-output-tokens 400 --price-per-1m-in 3.0 --price-per-1m-out 15.0 \
      --cache-hit-rate 0.35 --small-model-route-rate 0.45 --small-model-discount 0.85
  uv run python tools/finops_calc.py gpu --params-b 70 --quant-bits 4 \
      --ctx-len 8192 --concurrency 32
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class SystemCapacityResult:
    avg_rps: float
    peak_rps: float
    required_concurrency: float
    storage_tb: float
    egress_gb_per_month: float


@dataclass(frozen=True)
class LLMFinOpsResult:
    baseline_monthly_usd: float
    optimized_monthly_usd: float
    monthly_savings_usd: float
    annual_savings_usd: float
    savings_pct: float


@dataclass(frozen=True)
class GPUVramResult:
    weights_gb: float
    kv_cache_gb: float
    overhead_gb: float
    total_vram_gb: float
    recommended_h100_80gb_gpus: int


def calculate_system_capacity(
    *,
    rps: float,
    avg_latency_ms: float,
    payload_kb: float,
    years: float = 3.0,
    peak_multiplier: float = 3.0,
) -> SystemCapacityResult:
    if rps < 0 or avg_latency_ms < 0 or payload_kb < 0 or years <= 0 or peak_multiplier < 1:
        raise ValueError("All inputs must be non-negative (years > 0, peak_multiplier >= 1).")

    peak_rps = rps * peak_multiplier
    # Little's Law: L = lambda * W
    concurrency = peak_rps * (avg_latency_ms / 1000.0)
    seconds_per_year = 86_400.0 * 365.0
    total_kb = rps * payload_kb * seconds_per_year * years
    storage_tb = total_kb / (1024.0 * 1024.0 * 1024.0)
    egress_gb_per_month = (rps * payload_kb * 86_400.0 * 30.0) / (1024.0 * 1024.0)

    return SystemCapacityResult(
        avg_rps=round(rps, 2),
        peak_rps=round(peak_rps, 2),
        required_concurrency=round(concurrency, 2),
        storage_tb=round(storage_tb, 4),
        egress_gb_per_month=round(egress_gb_per_month, 2),
    )


def calculate_llm_finops(
    *,
    monthly_queries: int,
    avg_input_tokens: int,
    avg_output_tokens: int,
    price_per_1m_in: float,
    price_per_1m_out: float,
    cache_hit_rate: float = 0.0,
    small_model_route_rate: float = 0.0,
    small_model_discount: float = 0.80,
) -> LLMFinOpsResult:
    if monthly_queries < 0 or avg_input_tokens < 0 or avg_output_tokens < 0:
        raise ValueError("Query and token counts must be non-negative.")
    if not (0.0 <= cache_hit_rate <= 1.0):
        raise ValueError("cache_hit_rate must be between 0.0 and 1.0.")
    if not (0.0 <= small_model_route_rate <= 1.0):
        raise ValueError("small_model_route_rate must be between 0.0 and 1.0.")
    if not (0.0 <= small_model_discount <= 1.0):
        raise ValueError("small_model_discount must be between 0.0 and 1.0.")

    in_m = (monthly_queries * avg_input_tokens) / 1_000_000.0
    out_m = (monthly_queries * avg_output_tokens) / 1_000_000.0
    baseline = (in_m * price_per_1m_in) + (out_m * price_per_1m_out)

    # Queries surviving semantic cache
    uncached_ratio = 1.0 - cache_hit_rate
    # Of uncached queries, some route to a cheaper small model
    blended_multiplier = uncached_ratio * (
        (1.0 - small_model_route_rate) + (small_model_route_rate * (1.0 - small_model_discount))
    )
    baseline_r = round(baseline, 2)
    optimized_r = round(baseline * blended_multiplier, 2)
    monthly_savings_r = round(baseline_r - optimized_r, 2)
    annual_savings_r = round(monthly_savings_r * 12.0, 2)
    pct = (monthly_savings_r / baseline_r * 100.0) if baseline_r > 0 else 0.0

    return LLMFinOpsResult(
        baseline_monthly_usd=baseline_r,
        optimized_monthly_usd=optimized_r,
        monthly_savings_usd=monthly_savings_r,
        annual_savings_usd=annual_savings_r,
        savings_pct=round(pct, 2),
    )


def estimate_gpu_vram(
    *,
    params_b: float,
    quant_bits: int = 4,
    ctx_len: int = 8192,
    concurrency: int = 16,
    kv_bytes_per_token_per_b_param: float = 0.000018,
) -> GPUVramResult:
    """Rough sizing rule for LLM serving: Weights + KV Cache + 15% runtime/activation overhead."""
    if params_b <= 0 or quant_bits <= 0 or ctx_len <= 0 or concurrency <= 0:
        raise ValueError("All GPU sizing parameters must be positive.")

    weights_gb = params_b * (quant_bits / 8.0)
    # Approximate FP16 KV-cache scaling across concurrent active sequences
    kv_cache_gb = params_b * ctx_len * concurrency * kv_bytes_per_token_per_b_param
    overhead_gb = (weights_gb + kv_cache_gb) * 0.15
    total = weights_gb + kv_cache_gb + overhead_gb
    gpus = max(1, int(-(-total // 76.0)))  # ~76 GB usable per 80 GB H100/A100

    return GPUVramResult(
        weights_gb=round(weights_gb, 2),
        kv_cache_gb=round(kv_cache_gb, 2),
        overhead_gb=round(overhead_gb, 2),
        total_vram_gb=round(total, 2),
        recommended_h100_80gb_gpus=gpus,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Spartan System Capacity, GPU & FinOps Calculator")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_sys = sub.add_parser("system", help="Little's Law concurrency, storage & egress math")
    p_sys.add_argument("--rps", type=float, required=True)
    p_sys.add_argument("--avg-latency-ms", type=float, required=True)
    p_sys.add_argument("--payload-kb", type=float, required=True)
    p_sys.add_argument("--years", type=float, default=3.0)
    p_sys.add_argument("--peak-multiplier", type=float, default=3.0)

    p_llm = sub.add_parser("llm", help="LLM token FinOps & semantic cache/routing savings")
    p_llm.add_argument("--monthly-queries", type=int, required=True)
    p_llm.add_argument("--avg-input-tokens", type=int, required=True)
    p_llm.add_argument("--avg-output-tokens", type=int, required=True)
    p_llm.add_argument("--price-per-1m-in", type=float, required=True)
    p_llm.add_argument("--price-per-1m-out", type=float, required=True)
    p_llm.add_argument("--cache-hit-rate", type=float, default=0.35)
    p_llm.add_argument("--small-model-route-rate", type=float, default=0.45)
    p_llm.add_argument("--small-model-discount", type=float, default=0.85)

    p_gpu = sub.add_parser("gpu", help="Approximate LLM GPU VRAM & KV-cache sizing")
    p_gpu.add_argument("--params-b", type=float, required=True)
    p_gpu.add_argument("--quant-bits", type=int, default=4)
    p_gpu.add_argument("--ctx-len", type=int, default=8192)
    p_gpu.add_argument("--concurrency", type=int, default=16)

    args = parser.parse_args()
    if args.mode == "system":
        print(
            calculate_system_capacity(
                rps=args.rps,
                avg_latency_ms=args.avg_latency_ms,
                payload_kb=args.payload_kb,
                years=args.years,
                peak_multiplier=args.peak_multiplier,
            )
        )
    elif args.mode == "llm":
        print(
            calculate_llm_finops(
                monthly_queries=args.monthly_queries,
                avg_input_tokens=args.avg_input_tokens,
                avg_output_tokens=args.avg_output_tokens,
                price_per_1m_in=args.price_per_1m_in,
                price_per_1m_out=args.price_per_1m_out,
                cache_hit_rate=args.cache_hit_rate,
                small_model_route_rate=args.small_model_route_rate,
                small_model_discount=args.small_model_discount,
            )
        )
    elif args.mode == "gpu":
        print(
            estimate_gpu_vram(
                params_b=args.params_b,
                quant_bits=args.quant_bits,
                ctx_len=args.ctx_len,
                concurrency=args.concurrency,
            )
        )


if __name__ == "__main__":
    main()
