# ARCHEON Desktop Agent M2 — Vision model audit

Status: `AUDITED / NO MODEL DOWNLOADED` (2026-08-24)

The figures below are screening estimates, not Ryzen 5 5600GT benchmarks. First-inference latency and post-unload RAM remain deliberately unverified until the user authorizes a download and a controlled benchmark.

| Candidate | Download (Q4 + projector) | Estimated working RAM | CPU / future AMD | UI / OCR quality | License / redistribution | Windows integration | Verdict |
|---|---:|---:|---|---|---|---|---|
| Qwen3-VL-2B-Instruct | 1.03 GiB + 0.41 GiB | 2.3–3.5 GiB | AVX2 CPU; llama.cpp Vulkan/HIP path available | Strongest small candidate for GUI, document OCR and multilingual visual reasoning; must benchmark Spanish UI | Apache-2.0; commercial redistribution permitted with notices | Official Qwen GGUF and llama.cpp Qwen3-VL architecture support; newer/maturing path | **Recommended first benchmark** |
| SmolVLM2-2.2B-Instruct | 1.04 GiB + 0.55 GiB | 2.4–3.6 GiB | AVX2 CPU; Vulkan/HIP possible | Good lightweight general vision/video baseline; expected weaker dense OCR/UI reasoning | Apache-2.0 | Official ggml-org Q4_K_M and mature llama.cpp multimodal recipe | **Fallback / control baseline** |
| InternVL3-2B-Instruct | approximately 1.2–1.8 GiB after quantization | 2.5–4.0 GiB | CPU possible; conversion-specific validation required | Competitive multilingual vision; custom-code path adds integration risk | Project MIT; Qwen2.5 component Apache-2.0 | Hugging Face path requires `trust_remote_code`; llama.cpp support has variant caveats | **Do not choose first** |
| Gemma 3 4B IT | approximately 2.5–3.2 GiB quantized + projector | 4–6 GiB | CPU heavier; AMD offload possible | Strong general image understanding and 140+ languages | Gated Gemma terms, redistribution obligations require legal review | llama.cpp supports Gemma 3, but download is gated and materially heavier | **Optional later benchmark** |
| Qwen2.5-VL-3B-Instruct | approximately 2–3 GiB quantized + projector | 3.5–5 GiB | CPU feasible but heavier | Excellent published DocVQA/TextVQA and screen grounding | Qwen Research License for this repository restricts commercial use without a separate license | llama.cpp support exists | **Rejected for ARCHEON commercial base** |

## Decision

Qwen3-VL-2B-Instruct is the current first benchmark candidate, not a permanent product decision. It combines the most promising small-model UI/OCR capability with Apache-2.0 licensing and an official GGUF repository. SmolVLM2 remains the control baseline because its llama.cpp packaging is established and its footprint is similarly small.

No model, projector or visual runtime is included in Desktop Agent M2. Vision stays unloaded at idle. When authorized, the runtime must use `AppPaths.model_dir`, verify an official hash before loading, capture the active window first, resize bounded input, retain screenshots in memory only, and unload both model and projector after inactivity.

## Sources checked

- [Qwen3-VL-2B-Instruct official model card](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)
- [Qwen3-VL-2B-Instruct official GGUF files](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/tree/main)
- [SmolVLM2 llama.cpp GGUF repository](https://huggingface.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF)
- [InternVL3-2B-Instruct model card](https://huggingface.co/OpenGVLab/InternVL3-2B-Instruct)
- [Gemma 3 4B IT model card and gated terms](https://huggingface.co/google/gemma-3-4b-it)
- [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)
- [llama.cpp supported CPU/GPU backends](https://github.com/ggml-org/llama.cpp/blob/master/README.md)

