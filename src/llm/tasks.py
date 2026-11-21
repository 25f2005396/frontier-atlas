import asyncio
import json

from src.llm.grounding import validate_product
from src.llm.orchestrator import LLMOrchestrator
from src.utils.logging import setup_logging

PRODUCT_SYSTEM = (
    "You extract structured data from website text. Use ONLY the text provided. "
    "Never use outside knowledge. If something is not stated in the text, return null. "
    "Respond with a single JSON object and nothing else."
)


def product_prompt(company: str):
    def build(text: str) -> str:
        return (
            f"Company: {company}\n\n"
            "From the TEXT below, extract the company's main product. Return a JSON object with keys:\n"
            '  "product_name": the product name exactly as written in the text, or null\n'
            '  "pricing_model": one of FREE, FREEMIUM, PAID, ENTERPRISE, or null if pricing is not stated\n'
            '  "pricing_evidence": one sentence copied word for word from the text that supports pricing_model, or null\n\n'
            "TEXT:\n" + text
        )
    return build


async def extract_product(llm: LLMOrchestrator, company: str, page_text: str):
    result = await llm.extract(page_text, PRODUCT_SYSTEM, product_prompt(company))
    clean, reason = validate_product(result.data, result.text_sent)
    return clean, reason, result.provider


if __name__ == "__main__":
    setup_logging()
    sample = (
        "Acme Notes is a note-taking app for teams.\n"
        "Acme Notes Free includes up to 5 notebooks.\n"
        "Acme Notes Pro costs $8 per month and adds unlimited notebooks."
    )

    async def main():
        async with LLMOrchestrator() as llm:
            print(json.dumps(await extract_product(llm, "Acme", sample), indent=1))

    asyncio.run(main())