from datetime import date

# Model ID Constants
GEMINI_4_ARGON = "gemini-4-argon"
GEMINI_4_CARBON = "gemini-4-carbon"
GEMINI_4_HYDROGEN = "gemini-4-hydrogen"
GEMINI_3_8_FLASH = "gemini-3.8-flash"
GEMINI_3_7_FLASH = "gemini-3.7-flash"
GEMINI_3_6_FLASH = "gemini-3.6-flash"
GEMINI_3_5_FLASH = "gemini-3.5-flash"
GEMINI_3_5_FLASH_LITE = "gemini-3.5-flash-lite"
GEMINI_3_5_TRANSCRIBE = "gemini-3.5-transcribe"
GEMINI_3_1_PRO = "gemini-3.1-pro-preview"
GEMINI_3_1_FLASH_LITE = "gemini-3.1-flash-lite"
GEMINI_3_1_FLASH_IMAGE = "gemini-3.1-flash-image"
GEMINI_3_1_FLASH_LITE_IMAGE = "gemini-3.1-flash-lite-image"
GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"
GEMINI_3_PRO_IMAGE = "gemini-3-pro-image"
GEMINI_NANO_BANANA_2_1 = "gemini-nano-banana-2.1"

MODELS_CONFIG = {
    "GEMINI_4_ARGON": {
        "model_id": GEMINI_4_ARGON,
        "aistudio_name": "gemini-4-argon",
        "pricing": {
            "input": 2,
            "output": 10,
            "thinking": 10,
        },
        "discount_schedule": {
            "has_discount": True,
            "discount_note": "Promotional pricing (50% credits back on net spend) through November 30, 2026",
            "current_pricing": {
                "input": 2,
                "output": 10,
                "thinking": 10,
            },
            "switch_date": "2026-12-01",
            "standard_pricing": {
                "input": 4,
                "output": 20,
                "thinking": 20,
            },
        },
    },
    "GEMINI_4_CARBON": {
        "model_id": GEMINI_4_CARBON,
        "aistudio_name": "gemini-4-carbon",
        "pricing": {
            "input": 2,
            "output": 10,
            "thinking": 10,
        },
        "discount_schedule": {
            "has_discount": True,
            "discount_note": "Promotional pricing (50% credits back on net spend) through November 30, 2026",
            "current_pricing": {
                "input": 2,
                "output": 10,
                "thinking": 10,
            },
            "switch_date": "2026-12-01",
            "standard_pricing": {
                "input": 4,
                "output": 20,
                "thinking": 20,
            },
        },
    },
    "GEMINI_4_HYDROGEN": {
        "model_id": GEMINI_4_HYDROGEN,
        "aistudio_name": "gemini-4-hydrogen",
        "pricing": {
            "input": 1.5,
            "output": 7.5,
            "thinking": 7.5,
        },
        "discount_schedule": None,
    },
    "GEMINI_3_8_FLASH": {
        "model_id": GEMINI_3_8_FLASH,
        "aistudio_name": "gemini-3.8-flash",
        "pricing": {
            "input": 0.75,
            "output": 3.75,
            "thinking": 3.75,
        },
        "discount_schedule": {
            "has_discount": True,
            "discount_note": "Introductory 50% pricing through December 31, 2026",
            "current_pricing": {
                "input": 0.75,
                "output": 3.75,
                "thinking": 3.75,
            },
            "switch_date": "2027-01-01",
            "standard_pricing": {
                "input": 1.5,
                "output": 7.5,
                "thinking": 7.5,
            },
        },
    },
    "GEMINI_3_7_FLASH": {
        "model_id": GEMINI_3_7_FLASH,
        "aistudio_name": "gemini-3.7-flash",
        "pricing": {
            "input": 0.75,
            "output": 3.75,
            "thinking": 3.75,
        },
        "discount_schedule": {
            "has_discount": True,
            "discount_note": "Introductory 50% pricing through December 31, 2026",
            "current_pricing": {
                "input": 0.75,
                "output": 3.75,
                "thinking": 3.75,
            },
            "switch_date": "2027-01-01",
            "standard_pricing": {
                "input": 1.5,
                "output": 7.5,
                "thinking": 7.5,
            },
        },
    },
    "GEMINI_3_6_FLASH": {
        "model_id": GEMINI_3_6_FLASH,
        "aistudio_name": "gemini-3.6-flash",
        "pricing": {
            "input": 0.75,
            "output": 3.75,
            "thinking": 3.75,
        },
        "discount_schedule": {
            "has_discount": True,
            "discount_note": "Introductory 50% pricing through December 31, 2026",
            "current_pricing": {
                "input": 0.75,
                "output": 3.75,
                "thinking": 3.75,
            },
            "switch_date": "2027-01-01",
            "standard_pricing": {
                "input": 1.5,
                "output": 7.5,
                "thinking": 7.5,
            },
        },
    },
    "GEMINI_3_5_FLASH": {
        "model_id": GEMINI_3_5_FLASH,
        "aistudio_name": "gemini-3.5-flash",
        "pricing": {
            "input": 1.5,
            "output": 9,
            "thinking": 9,
        },
        "discount_schedule": None,
    },
    "GEMINI_3_5_FLASH_LITE": {
        "model_id": GEMINI_3_5_FLASH_LITE,
        "aistudio_name": "gemini-3.5-flash-lite",
        "pricing": {
            "input": 0.3,
            "output": 2.5,
            "thinking": 2.5,
        },
        "discount_schedule": None,
    },
    "GEMINI_3_5_TRANSCRIBE": {
        "model_id": GEMINI_3_5_TRANSCRIBE,
        "aistudio_name": "gemini-3.5-transcribe",
        "pricing": {
            "input": 2,
            "output": 12,
            "thinking": 12,
        },
        "discount_schedule": None,
    },
    "GEMINI_3_1_PRO": {
        "model_id": GEMINI_3_1_PRO,
        "aistudio_name": "gemini-3.1-pro-preview",
        "pricing": {
            "input": 2,
            "output": 12,
            "thinking": 12,
        },
        "discount_schedule": None,
    },
    "GEMINI_3_1_FLASH_LITE": {
        "model_id": GEMINI_3_1_FLASH_LITE,
        "aistudio_name": "gemini-3.1-flash-lite",
        "pricing": {
            "input": 0.25,
            "output": 1.5,
            "thinking": 1.5,
        },
        "discount_schedule": None,
    },
    "GEMINI_3_1_FLASH_IMAGE": {
        "model_id": GEMINI_3_1_FLASH_IMAGE,
        "aistudio_name": "gemini-3.1-flash-image",
        "pricing": {
            "input": 0.5,
            "output": 3,
            "thinking": 3,
            "image_output_per_1m_tokens": 60,
        },
        "discount_schedule": None,
    },
    "GEMINI_3_1_FLASH_LITE_IMAGE": {
        "model_id": GEMINI_3_1_FLASH_LITE_IMAGE,
        "aistudio_name": "gemini-3.1-flash-lite-image",
        "pricing": {
            "input": 0.25,
            "output": 1.5,
            "thinking": 1.5,
            "image_output_per_1m_tokens": 30,
        },
        "discount_schedule": None,
    },
    "GEMINI_3_FLASH_PREVIEW": {
        "model_id": GEMINI_3_FLASH_PREVIEW,
        "aistudio_name": "gemini-3-flash-preview",
        "pricing": {
            "input": 0.5,
            "output": 3,
            "thinking": 3,
        },
        "discount_schedule": None,
    },
    "GEMINI_3_PRO_IMAGE": {
        "model_id": GEMINI_3_PRO_IMAGE,
        "aistudio_name": "gemini-3-pro-image",
        "pricing": {
            "input": 2,
            "output": 12,
            "thinking": 12,
            "image_output_per_1m_tokens": 120,
        },
        "discount_schedule": None,
    },
    "GEMINI_NANO_BANANA_2_1": {
        "model_id": GEMINI_NANO_BANANA_2_1,
        "aistudio_name": "gemini-nano-banana-2.1",
        "pricing": {
            "input": 1.5,
            "output": 30,
            "thinking": 30,
        },
        "discount_schedule": None,
    },
}


def get_aistudio_name(model: str) -> str:
    """Resolves a model ID or MODELS_CONFIG key to its AI Studio URL model identifier."""
    if model in MODELS_CONFIG:
        return MODELS_CONFIG[model].get("aistudio_name", MODELS_CONFIG[model]["model_id"])
    for info in MODELS_CONFIG.values():
        if info["model_id"] == model:
            return info.get("aistudio_name", model)
    return model


def get_resolved_pricing() -> dict[str, dict]:
    """Builds the pricing dict keyed by model_id, automatically resolving active discounts."""
    today = date.today().isoformat()
    resolved_pricing = {}

    for info in MODELS_CONFIG.values():
        model_id = info["model_id"]
        schedule = info.get("discount_schedule")

        if schedule and schedule.get("has_discount"):
            if today < schedule["switch_date"]:
                resolved_pricing[model_id] = schedule["current_pricing"]
            else:
                resolved_pricing[model_id] = schedule["standard_pricing"]
        else:
            resolved_pricing[model_id] = info["pricing"]

    return resolved_pricing
