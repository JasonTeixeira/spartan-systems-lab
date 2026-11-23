# Local platform delivery contract

```sh
python3 labs/platform-delivery-contract/demo.py
python3 -m unittest discover -s tests -p 'test_platform_delivery_contract.py' -v
```

The fixed, owned JSON artifacts contain only a name and one of three predefined modes. They are data, not executable uploads. A `Platform` starts with a baseline tested across its complete toy integer domain 0–5. A release validates bytes, schema, policy and bounded request list, calculates the artifact SHA-256, runs a deliberately incomplete local test set `[2,3]`, then applies the local-target policy. An allowed candidate is temporarily selected for an actual in-process canary; its outputs and errors are recorded against the offered cases along with local elapsed nanoseconds. More errors than the policy permits restores the previous selected config and probes that restored config at zero. The recorded selection names **and hashes** distinguish two differently encoded artifacts with the same name.

The recovered zero output can be `null`: an earlier candidate might have passed a limited canary and itself be faulty. Rollback is selection recovery, not proof of restored health; check the recovery output. An unexpected Python exception during the modeled canary restores the previous in-memory selection and propagates. Abrupt process loss is not modeled. Test-failed or policy-denied candidates are not selected. Times include local interpreter work and are not production latency measurements. There are at most 64 validated attempts per instance, 4096 bytes per artifact, and 20 canary cases per attempt; no history persists across restarts.

The [actual author observation](../../proof/platform-delivery-author-observation-v2.json) contains local outputs and hashes. The lesson explains the fixed input domain, partial tests, recovery limitation and changed case. This is not a CI/CD provider, authenticated policy, production service, cloud deployment, build system, durable audit, network traffic or human review.
