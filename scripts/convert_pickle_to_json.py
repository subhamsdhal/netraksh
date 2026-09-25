import os
import sys
import pickle
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SECURITY WARNING: This script uses pickle.load() to migrate legacy models.
# Unpickling is inherently unsafe because it can execute arbitrary code contained in the pickle file.
# ONLY RUN THIS SCRIPT ON .pkl FILES THAT YOU ABSOLUTELY TRUST AND HAVE VERIFIED.
# DO NOT run this on unverified files downloaded from the internet.

def convert_model(input_path: str, output_path: str):
    if not os.path.exists(input_path):
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)
        
    logger.info(f"Loading legacy pickle model from {input_path}...")
    try:
        with open(input_path, "rb") as f:
            model = pickle.load(f)
    except Exception as e:
        logger.error(f"Failed to unpickle model: {e}")
        sys.exit(1)
        
    # Extract Logistic Regression parameters
    if not hasattr(model, "coef_") or not hasattr(model, "intercept_"):
        logger.error("Model does not appear to be a standard scikit-learn LogisticRegression (missing coef_ or intercept_).")
        sys.exit(1)
        
    coef = model.coef_
    if coef.shape[1] != 4:
        logger.error(f"Expected 4 features, got {coef.shape[1]}")
        sys.exit(1)
        
    # Mapping assumed order: d, t, s, h
    weights = {
        "d": float(coef[0][0]),
        "t": float(coef[0][1]),
        "s": float(coef[0][2]),
        "h": float(coef[0][3])
    }
    intercept = float(model.intercept_[0])
    
    json_model = {
        "version": 1,
        "weights": weights,
        "intercept": intercept,
        "metadata": {
            "source": "migrated_from_pickle",
            "features": ["detector_confidence", "temporal_score", "scene_quality", "health_quality"]
        }
    }
    
    try:
        with open(output_path, "w") as f:
            json.dump(json_model, f, indent=2)
        logger.info(f"Successfully converted model to JSON and saved to {output_path}")
    except Exception as e:
        logger.error(f"Failed to write JSON model: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python convert_pickle_to_json.py <input.pkl> <output.json>")
        print("WARNING: This script will execute pickle.load(). Only run on trusted files!")
        sys.exit(1)
        
    convert_model(sys.argv[1], sys.argv[2])
