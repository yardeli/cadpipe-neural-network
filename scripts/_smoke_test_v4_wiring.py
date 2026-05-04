"""Smoke test: load v4 weights, register as plasmanet_v4, score Park AIR-7.

Confirms the surrogate plugs into the scoring framework cleanly so the
other Claude instance's BO loop can call score_candidate(evaluator=
"plasmanet_v4", ...) without surprises.
"""
import time
import torch
from plasmanet.mechanism_search import (
    PARK_47, BENCHMARKS, MechanismSurrogate,
    register_surrogate_evaluator, park_air7,
)
from plasmanet.mechanism_search.scoring import score_candidate


def main():
    print("loading v4 weights ...")
    t0 = time.time()
    model = MechanismSurrogate(freestream_dim=4, mechanism_dim=47,
                                hidden_dim=512, n_layers=4)
    model.load_state_dict(torch.load(
        "/home/yarden/mechanism_search_results/surrogate_v4.pt"))
    model.eval()
    print(f"  loaded in {time.time()-t0:.2f}s")

    register_surrogate_evaluator(model, name="plasmanet_v4")
    print("registered as plasmanet_v4")

    mech = park_air7()
    result = score_candidate(
        mechanism_name="Park_AIR7",
        evaluator="plasmanet_v4",
        evaluator_input={"mechanism": mech},
        benchmark="ram_c_61km_M22.5",
    )
    pb = result.per_benchmark[0]
    print(f"surrogate AIR-7 ne = {pb.ne_predicted_m3:.3e}")
    print(f"composite_score    = {result.composite_score:.4f}")
    bk = BENCHMARKS["ram_c_61km_M22.5"]
    print(f"published ne       = {bk.ne_published_m3:.3e}")

    # Throughput probe
    t0 = time.time()
    for _ in range(1000):
        score_candidate(
            mechanism_name="Park_AIR7",
            evaluator="plasmanet_v4",
            evaluator_input={"mechanism": mech},
            benchmark="ram_c_61km_M22.5",
        )
    dt = time.time() - t0
    print(f"throughput: {1000/dt:.0f} evals/sec ({dt*1000:.1f} ms / 1000 evals)")
    print("OK")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
