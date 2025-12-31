"""
Prompt generator using Ollama for local inference.
Incorporates temporal context (time of day, day of week, and holidays)
for more contextually aware prompts.
"""

import logging
import time

from ..plugins import get_context_with_descriptions, get_temporal_descriptor
from ..utils.config import Config
from ..utils.error_handler import PromptError, handle_errors
from ..utils.metrics import GenerationMetrics


class PromptGenerator:
    def __init__(self, config: Config):
        """Initialize prompt generator with configuration."""
        self.config = config
        self.model_name = config.model.ollama_model
        # Regular example prompts (no Lora)
        self.regular_example_prompts = [
            "Cozy cafe: Steam from coffee cups, readers in corners, frost patterns on windows cast golden morning light, prismatic reflections dance.",
            "Futuristic market: Holographic stalls mix with traditional ones, sci-fi foods under crystal dome, rainbow light filters through.",
        ]
        # Lora-specific example prompts
        self.lora_example_prompts = [
            "Magical post office with '<lora_name>' as the postmaster: Sorting letters on floating belts, mechanical reindeer power machines, fiber-optic antlers glow."
        ]
        self.conversation_history = []
        self.logger = logging.getLogger(__name__)

    @handle_errors(error_type=PromptError, retries=2)
    async def generate_prompt(self) -> str:
        """Generate a 60 word image prompt using Ollama with conversation context."""
        try:
            import ollama

            metrics = GenerationMetrics(model_name=self.model_name)
            start_time = time.time()

            # Get context with plugin descriptions
            context_data = get_context_with_descriptions()
            temporal_context = get_temporal_descriptor()

            # Log plugin contributions
            self.logger.info("Plugin contributions:")
            for result in context_data["results"]:
                self.logger.info(f"  {result.name}: {result.value} - {result.description}")

            # Extract Lora keyword if present
            lora_keyword = None
            for result in context_data["results"]:
                if result.name == "lora" and result.value:
                    lora_keyword = result.value
                    break

            # Build system context with plugin information
            system_context_parts = [
                "You are a creative prompt generator for image generation.",
                "Generate unique and imaginative prompts that would inspire beautiful AI-generated images.",
                "IMPORTANT: Prompts MUST be concise and fit within 77 tokens (approximately 60 words).",
                "IMPORTANT: Do not have a preamble or explain the prompt, output ONLY the prompt itself.",
                "Focus on vivid, impactful descriptions using fewer, carefully chosen words.",
                "\nAvailable context from plugins:",
                *[f"- {desc}" for desc in context_data["descriptions"]],
                f"\nCurrent temporal context: {temporal_context}",
                "Begin the prompt with this temporal context, then add a concise but vivid scene description.",
                "Keep the final combined prompt (including context) within the 77 token limit.",
                "You may choose which context elements to incorporate based on relevance.",
            ]

            # Only add Lora-specific instructions if a Lora keyword is available
            if lora_keyword:
                system_context_parts.extend(
                    [
                        "\nIMPORTANT: You MUST make the Lora keyword a central subject or character in the scene.",
                        "The Lora keyword should be in single quotes and be an active participant in the scene.",
                        "Example format: '[temporal/style context]: [scene with Lora as subject]'",
                        "For example: 'scene with '<keyword>' as the main character doing something'",
                    ]
                )

            system_context = "\n".join(system_context_parts)

            if lora_keyword:
                system_context += f"\nCurrent Lora keyword that MUST be used as a subject in single quotes: '{lora_keyword}'"
                system_context += "\nMake sure the Lora keyword is a central character or subject in the scene, not just mentioned."

            self.logger.info(f"Generated temporal context: {temporal_context}")

            # Initialize conversation if empty
            if not self.conversation_history:
                # Select appropriate example prompts based on whether a Lora keyword is available
                example_prompts = self.regular_example_prompts.copy()
                if lora_keyword:
                    example_prompts.extend(self.lora_example_prompts)

                # Create user message with examples
                user_message_parts = [
                    "Here are some example prompts:",
                    *[f"Example {i + 1}: {prompt}" for i, prompt in enumerate(example_prompts)],
                    "\nGenerate a new prompt that is different from these examples but equally creative.",
                ]

                # Add Lora-specific instruction if a Lora keyword is available
                if lora_keyword:
                    user_message_parts.append(
                        "Make the Lora keyword the central subject or character in the scene."
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
            )

            # Process and log the generated prompt
            new_prompt = response.message.content.strip()
            # Clean up Unicode characters that cause Windows console issues
            new_prompt = (
                new_prompt.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "--")
            )
            new_prompt = (
                new_prompt.replace("\u2018", "'")
                .replace("\u2019", "'")
                .replace("\u201c", '"')
                .replace("\u201d", '"')
            )
            self.logger.info(f"Raw generated prompt: {new_prompt}")

            # Add new prompt to conversation history
            self.conversation_history.append({"role": "assistant", "content": new_prompt})
            # Create next user message
            next_message = "Generate another unique prompt, different from previous ones."
            if lora_keyword:
                next_message += (
                    " Remember to make the Lora keyword the central subject in the scene."
                )

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
