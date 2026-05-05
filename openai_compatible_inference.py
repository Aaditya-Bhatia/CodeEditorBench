import argparse
import asyncio
import importlib
import jsonlines
import os
import sys
import time

import torch
from openai import AsyncOpenAI
from tqdm import tqdm

from dataset import JsonlDataset, my_collate_fn

sys.path.append("./prompt_function/")


def build_client(api_base: str, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key,
        base_url=api_base.rstrip("/"),
        timeout=600,
        max_retries=2,
    )


SUPPORTED_PROMPT_MODELS = {
    "wizardcoder",
    "deepseek",
    "magicoder",
    "codefuse",
    "octocoder",
    "codellama",
    "phind",
    "codellama-inst",
}


def infer_model_choice(base_model: str):
    max_model_len = 16384
    if "Wizard" in base_model:
        model_choice = "wizardcoder"
        group = "group1"
        if "15B" in base_model:
            max_model_len = 8192
    elif "Magic" in base_model:
        model_choice = "magicoder"
        group = "group1"
        max_model_len = 32768
        if "CL" in base_model:
            max_model_len = 16384
    elif "octo" in base_model:
        model_choice = "octocoder"
        group = "group1"
        max_model_len = 8192
    elif "codefuse" in base_model:
        model_choice = "codefuse"
        group = "group1"
    elif "deepseek" in base_model:
        model_choice = "deepseek"
        group = "group1"
    elif "Phind" in base_model:
        model_choice = "phind"
        group = "group1"
    elif "Instruct-hf" in base_model:
        model_choice = "codellama-inst"
        group = "group1"
    elif "CodeLlama-34b-hf" in base_model:
        model_choice = "codellama"
        group = "group1"
    elif "bloom" in base_model:
        model_choice = "bloom"
        group = "group1"
    elif "OpenCode" in base_model:
        model_choice = "deepseek"
        group = "group1"
    else:
        raise ValueError(f"Invalid model name: {base_model}")
    return model_choice, group, max_model_len


def build_sampling_config(
    num_of_sequences: int,
    temperature: float = None,
    top_p: float = None,
    max_tokens: int = 2048,
    top_k: int = None,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
):
    if num_of_sequences == 1:
        resolved_temperature = 0.0 if temperature is None else temperature
        resolved_top_p = 1.0 if top_p is None else top_p
        config = {
            "n": 1,
            "temperature": resolved_temperature,
            "top_p": resolved_top_p,
            "max_tokens": max_tokens,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
        }
        if top_k is not None:
            config["extra_body"] = {"top_k": top_k}
        return config
    resolved_temperature = 0.8 if temperature is None else temperature
    resolved_top_p = 0.9 if top_p is None else top_p
    config = {
        "n": num_of_sequences,
        "temperature": resolved_temperature,
        "top_p": resolved_top_p,
        "max_tokens": max_tokens,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
    }
    extra_body = {}
    if top_k is not None:
        extra_body["top_k"] = top_k
    elif num_of_sequences != 1:
        extra_body["top_k"] = 40
    if extra_body:
        config["extra_body"] = extra_body
    return config


async def _single_request(client: AsyncOpenAI, model: str, prompt: str, sampling_config, semaphore: asyncio.Semaphore):
    async with semaphore:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                **sampling_config,
            )
            return [choice.message.content or "" for choice in response.choices]
        except Exception as e:
            print(f"[WARN] Skipping prompt ({len(prompt)} chars): {e}")
            return None


async def generate_batch_async(client: AsyncOpenAI, model: str, batch_prompts, sampling_config, max_concurrent: int):
    semaphore = asyncio.Semaphore(max_concurrent)
    tasks = [_single_request(client, model, p, sampling_config, semaphore) for p in batch_prompts]
    return await asyncio.gather(*tasks)


def generate_batch(client: AsyncOpenAI, model: str, batch_prompts, sampling_config, max_concurrent: int):
    return asyncio.run(generate_batch_async(client, model, batch_prompts, sampling_config, max_concurrent))


def main():
    parser = argparse.ArgumentParser(description="Run CodeEditorBench inference against an OpenAI-compatible API server.")
    parser.add_argument("--base_model", required=True, type=str, help="Model name used for prompt selection and output naming.")
    parser.add_argument("--api_model", default=None, type=str, help="Exact model id exposed by the API server. Defaults to --base_model.")
    parser.add_argument("--prompt_model", default=None, type=str, help="Prompt formatting family. One of: wizardcoder, deepseek, magicoder, codefuse, octocoder, codellama, phind, codellama-inst.")
    parser.add_argument("--api_base", default=os.environ.get("OPENAI_API_BASE", "http://127.0.0.1:9351/v1"), type=str, help="OpenAI-compatible API base URL.")
    parser.add_argument("--api_key", default=os.environ.get("OPENAI_API_KEY", "EMPTY"), type=str, help="API key passed to the server.")
    parser.add_argument("--dataset", default="debug", type=str, help="Name of dataset.")
    parser.add_argument("--input_data_dir", default="./data/", type=str, help="Path to input data directory.")
    parser.add_argument("--output_data_dir", default="./greedy_result/", type=str, help="Path to output data directory.")
    parser.add_argument("--batch_size", default=64, type=int, help="Number of prompts per batch (all sent concurrently).")
    parser.add_argument("--max_concurrent", default=64, type=int, help="Max concurrent async requests to the API server.")
    parser.add_argument("--num_of_sequences", default=1, type=int, help="Number of sequences to generate.")
    parser.add_argument("--temperature", default=None, type=float, help="Sampling temperature override.")
    parser.add_argument("--top_p", default=None, type=float, help="Top-p override.")
    parser.add_argument("--top_k", default=None, type=int, help="Top-k override.")
    parser.add_argument("--max_tokens", default=2048, type=int, help="Max generation tokens.")
    parser.add_argument("--frequency_penalty", default=0.0, type=float, help="Frequency penalty.")
    parser.add_argument("--presence_penalty", default=0.0, type=float, help="Presence penalty.")
    parser.add_argument("--prompt_type", default="zero", type=str, help="Type of prompts, zero, three, or cot.")
    parser.add_argument("--start_idx", default=0, type=int, help="Start index for data processing.")
    parser.add_argument("--end_idx", default=-1, type=int, help="End index for data processing.")
    args = parser.parse_args()

    module = importlib.import_module(f"prompt_function.prompt_{args.dataset}")
    if args.prompt_model:
        if args.prompt_model not in SUPPORTED_PROMPT_MODELS:
            raise ValueError(f"Unsupported prompt model: {args.prompt_model}")
        model_choice = args.prompt_model
        group = "group1"
    else:
        model_choice, group, _ = infer_model_choice(args.base_model)
    if args.prompt_type == "cot" and model_choice == "codellama-inst":
        group = "cot"
    prompt_function = getattr(module, f"generate_prompt_{group}")

    sampling_config = build_sampling_config(
        args.num_of_sequences,
        temperature=args.temperature,
        top_p=args.top_p,
        max_tokens=args.max_tokens,
        top_k=args.top_k,
        frequency_penalty=args.frequency_penalty,
        presence_penalty=args.presence_penalty,
    )
    api_model = args.api_model or args.base_model
    input_data_path = os.path.join(args.input_data_dir, f"code_{args.dataset}_primary.jsonl")
    model_name = args.base_model.split("/")[-1].replace("-", "_").replace(".", "_")
    end = args.end_idx if args.end_idx != -1 else "end"

    if args.prompt_type == "zero":
        output_data_path = os.path.join(args.output_data_dir, f"code_{args.dataset}", f"{model_name}_{args.start_idx}_{end}.jsonl")
    elif args.prompt_type == "three":
        output_data_path = os.path.join(args.output_data_dir, f"code_{args.dataset}", f"Few_Shot_{model_name}_{args.start_idx}_{end}.jsonl")
    elif args.prompt_type == "cot":
        output_data_path = os.path.join(args.output_data_dir, f"code_{args.dataset}", f"Cot_{model_name}_{args.start_idx}_{end}.jsonl")
    else:
        raise ValueError("Invalid prompt type.")

    os.makedirs(os.path.dirname(output_data_path), exist_ok=True)
    meta_data_flag = False
    if os.path.exists(output_data_path):
        output_data = jsonlines.open(output_data_path, mode="a", flush=True)
        with open(output_data_path, "r") as f:
            line_count = sum(1 for _ in f)
        if line_count >= 1:
            meta_data_flag = True
        args.start_idx = max(0, line_count - 1)
    else:
        output_data = jsonlines.open(output_data_path, mode="w", flush=True)

    if args.end_idx == -1:
        args.end_idx = None
    dataset = JsonlDataset(input_data_path)[args.start_idx:args.end_idx]
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=args.batch_size, shuffle=False, collate_fn=my_collate_fn)
    client = build_client(args.api_base, args.api_key)

    start_time = time.time()
    for batch in tqdm(dataloader, desc="Inference"):
        if args.prompt_type == "zero":
            batch_prompts = prompt_function(batch, model_choice, "zero")
        elif args.prompt_type == "three":
            batch_prompts = prompt_function(batch, model_choice, "three")
        elif args.prompt_type == "cot":
            batch_prompts = prompt_function(batch, model_choice, "cot")
        else:
            raise ValueError("Invalid prompt type.")

        batch_output = generate_batch(client, api_model, batch_prompts, sampling_config, args.max_concurrent)
        if not meta_data_flag:
            meta_data_flag = True
            output_data.write(
                {
                    "model": args.base_model,
                    "api_model": api_model,
                    "api_base": args.api_base,
                    "greedy_search_decoding": sampling_config["n"] == 1 and sampling_config["temperature"] == 0.0,
                    "num_output": sampling_config["n"],
                    "temperature": sampling_config["temperature"],
                    "top_p": sampling_config["top_p"],
                    "top_k": sampling_config.get("extra_body", {}).get("top_k"),
                }
            )

        for idx, output in enumerate(batch_output):
            if output is None:
                continue
            if args.dataset == "debug":
                new_data = {
                    "problem_id": batch["idx"][idx].item(),
                    "completion_id": 0,
                    "language": batch["code_language"][idx],
                    "error_type": batch["type"][idx],
                    "difficulty": batch["difficulty"][idx],
                    "prompt": batch_prompts[idx],
                    "code": output,
                }
            elif args.dataset == "translate":
                new_data = {
                    "problem_id": batch["idx"][idx].item(),
                    "completion_id": 0,
                    "source_lang": batch["source_lang"][idx],
                    "target_lang": batch["target_lang"][idx],
                    "difficulty": batch["difficulty"][idx],
                    "prompt": batch_prompts[idx],
                    "code": output,
                }
            elif args.dataset == "polishment":
                new_data = {
                    "problem_id": batch["idx"][idx].item(),
                    "completion_id": 0,
                    "language": batch["source_lang"][idx],
                    "difficulty": batch["difficulty"][idx],
                    "prompt": batch_prompts[idx],
                    "code": output,
                }
            elif args.dataset == "switch":
                new_data = {
                    "problem_id": batch["idx"][idx].item(),
                    "completion_id": 0,
                    "language": batch["language"][idx],
                    "pair": batch["pair_id"][idx],
                    "prompt": batch_prompts[idx],
                    "code": output,
                }
            else:
                raise ValueError("Invalid dataset type.")
            output_data.write(new_data)

    end_time = time.time()
    print("Time used:", end_time - start_time)
    if len(dataloader) == 0:
        print("No data in the dataset.")
    else:
        print("Each batch time:", (end_time - start_time) / len(dataloader))


if __name__ == "__main__":
    main()
