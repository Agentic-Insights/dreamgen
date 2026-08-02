"""
Prompt generator using Ollama for local inference.
Incorporates temporal context (time of day, day of week, and holidays)
for more contextually aware prompts.
"""

import logging
import time
from typing import Optional

from ..plugins.lora import condition_prompt_for_lora
from ..utils.config import Config
from ..utils.error_handler import PromptError, handle_errors
from ..utils.generation_plan import GenerationPlan, resolve_generation_plan
from ..utils.metrics import GenerationMetrics
from ..utils.ollama import list_ollama_models, resolve_ollama_model


class PromptGenerator:
    def __init__(self, config: Config, generation_plan: Optional[GenerationPlan] = None):
        """Initialize prompt generator with configuration."""
        self.config = config
        self.generation_plan = generation_plan
        self.model_name = config.model.ollama_model
        # Regular example prompts (no Lora)
        self.regular_example_prompts = [
            "Cozy cafe: Steam from coffee cups, readers in corners, frost patterns on windows cast golden morning light, prismatic reflections dance.",
            "Futuristic market: Holographic stalls mix with traditional ones, sci-fi foods under crystal dome, rainbow light filters through.",
        ]
        self.conversation_history = []
        self.logger = logging.getLogger(__name__)

    @handle_errors(error_type=PromptError, retries=2)
    async def generate_prompt(self, meta_prompt: Optional[str] = None) -> str:
        """Generate a 60 word image prompt using Ollama with conversation context."""
        try:
            import ollama

            metrics = GenerationMetrics(model_name=self.model_name)
            start_time = time.time()

            available_models = list_ollama_models()
            resolved_model = resolve_ollama_model(
                available_models,
                self.config.model.ollama_model,
                "completion",
            )
            if not resolved_model:
                raise PromptError(
                    "No Ollama prompt model is available. Install a completion-capable model "
                    "such as 'qwen3.6', 'qwen3.5', or 'gemma4'."
                )

            if resolved_model != self.model_name:
                self.logger.warning(
                    "Configured Ollama prompt model %s is unavailable or not completion-capable; using %s instead",
                    self.model_name,
                    resolved_model,
                )
                self.model_name = resolved_model
                metrics.model_name = resolved_model

            # A service job supplies an immutable plan. Standalone prompt calls
            # resolve the same plan locally so adapter metadata is available and
            # no plugin is executed more than once.
            generation_plan = self.generation_plan or resolve_generation_plan(self.config)
            context_data = {
                "results": list(generation_plan.plugin_results),
                "descriptions": list(generation_plan.plugin_descriptions),
            }
            temporal_context = generation_plan.temporal_descriptor
            selected_lora = generation_plan.selected_lora

            # Log plugin contributions
            self.logger.info("Plugin contributions:")
            for result in context_data["results"]:
                self.logger.info(f"  {result.name}: {result.value} - {result.description}")

            # LoRA triggers are conditioning metadata. Style triggers must not
            # leak into the prose Ollama drafts, where the image model may treat
            # an opaque token as a character name or visible lettering.
            prompt_descriptions = [
                description
                for description in context_data["descriptions"]
                if not description.lower().startswith("lora:")
            ]

            base_system_prompt = (
                meta_prompt.strip()
                if meta_prompt
                else "\n".join(
                    [
                        "You are a creative prompt generator for image generation.",
                        "Generate unique and imaginative prompts that would inspire beautiful AI-generated images.",
                        "IMPORTANT: Prompts MUST be concise and fit within 77 tokens (approximately 60 words).",
                        "IMPORTANT: Do not have a preamble or explain the prompt, output ONLY the prompt itself.",
                        "Focus on vivid, impactful descriptions using fewer, carefully chosen words.",
                    ]
                )
            )

            # Build system context with plugin information
            system_context_parts = [
                base_system_prompt,
                "\nAvailable context from plugins:",
                *[f"- {desc}" for desc in prompt_descriptions],
                f"\nCurrent temporal context: {temporal_context}",
                "Begin the prompt with this temporal context, then add a concise but vivid scene description.",
                "Keep the final combined prompt (including context) within the 77 token limit.",
                "You may choose which context elements to incorporate based on relevance.",
            ]

            if selected_lora and selected_lora.kind == "object":
                system_context_parts.extend(
                    [
                        "\nAn object LoRA adapter is loaded for the primary depicted subject.",
                        "Use its exact subject token once, unquoted, as a visual entity rather than signage or written text.",
                        f"Exact object subject token: {selected_lora.keyword}",
                    ]
                )
            elif selected_lora:
                system_context_parts.extend(
                    [
                        "\nA style LoRA adapter is already loaded.",
                        "Describe only the natural visual scene and style; do not mention, quote, personify, spell, label, or render the adapter name or trigger token.",
                        "DreamGen appends any required style trigger after drafting.",
                    ]
                )

            system_context = "\n".join(system_context_parts)

            self.logger.info(f"Generated temporal context: {temporal_context}")

            # Initialize conversation if empty
            if not self.conversation_history:
                example_prompts = self.regular_example_prompts.copy()

                # Create user message with examples
                user_message_parts = [
                    "Here are some example prompts:",
                    *[f"Example {i + 1}: {prompt}" for i, prompt in enumerate(example_prompts)],
                    "\nGenerate a new prompt that is different from these examples but equally creative.",
                ]

                if selected_lora and selected_lora.kind == "object":
                    user_message_parts.append(
                        "Depict the declared object token as the primary visual subject, unquoted and not as text."
                    )

                self.conversation_history = [
                    {"role": "system", "content": system_context},
                    {"role": "user", "content": "\n".join(user_message_parts)},
                ]

            # Generate prompt with logging
            self.logger.info("Generating prompt with Ollama...")
            response = ollama.chat(
                model=self.model_name,
                messages=self.conversation_history,
                options={"temperature": self.config.model.ollama_temperature},
                # DreamGen's image backends need the same GPU immediately after
                # prompt drafting. Do not leave the Ollama completion model
                # resident and competing with Z-Image for VRAM.
                keep_alive=0,
            )

            # Process and log the generated prompt. Ollama can return either a
            # typed response object or a dict-like payload depending on client version.
            message = (
                response.get("message")
                if isinstance(response, dict)
                else getattr(response, "message")
            )
            content = (
                message.get("content") if isinstance(message, dict) else getattr(message, "content")
            )
            draft_prompt = content.strip()
            # Clean up Unicode characters that cause Windows console issues
            draft_prompt = (
                draft_prompt.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "--")
            )
            draft_prompt = (
                draft_prompt.replace("\u2018", "'")
                .replace("\u2019", "'")
                .replace("\u201c", '"')
                .replace("\u201d", '"')
            )
            self.logger.info(f"Raw generated prompt: {draft_prompt}")
            new_prompt = condition_prompt_for_lora(draft_prompt, selected_lora)
            if new_prompt != draft_prompt:
                self.logger.info(f"LoRA-conditioned prompt: {new_prompt}")

            # Add new prompt to conversation history
            self.conversation_history.append({"role": "assistant", "content": draft_prompt})
            # Create next user message
            next_message = "Generate another unique prompt, different from previous ones."
            if selected_lora and selected_lora.kind == "object":
                next_message += " Keep the declared object token as the unquoted visual subject."

            self.conversation_history.append({"role": "user", "content": next_message})

            # Update metrics
            metrics.generation_time = time.time() - start_time
            metrics.prompt = new_prompt
            metrics.prompt_tokens = len(new_prompt.split())

            return new_prompt

        except ImportError:
            raise PromptError("Please install ollama-python: pip install ollama")
        except Exception as e:
            raise PromptError(f"Error generating prompt: {str(e)}")

    @handle_errors(error_type=PromptError, retries=1)
    async def get_prompt_with_feedback(self) -> str:
        """Interactive prompt generation with user feedback."""
        while True:
            prompt = await self.generate_prompt()
            print("\nGenerated prompt:")
            print("-" * 80)
            print(prompt)
            print("-" * 80)

            choice = input(
                "\nOptions:\n1. Use this prompt\n2. Generate new prompt\n3. Edit this prompt\nChoice (1-3): "
            )

            if choice == "1":
                return prompt
            elif choice == "2":
                continue
            elif choice == "3":
                edited = input("\nEdit the prompt:\n")
                return edited.strip()
            else:
                print("Invalid choice, please try again.")

    def cleanup(self):
        """Clean up resources."""
        self.conversation_history = []
