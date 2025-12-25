import numpy as np
import faiss
import time
import os
import re
import random
import json
from django.conf import settings
from knowledge.models import KnowledgeBase
import logging
from typing import Dict, Any, Optional, Tuple
from ..gemini_service import GeminiResponseGenerator, SimpleVietnameseRestorer
import pandas as pd
import io
from ..external_api_service import external_api_service, StudentProfile
from qa_management.services import drive_service
from ..interaction_logger_service import interaction_logger
from ..query_response_cache import query_response_cache
from sentence_transformers.util import cos_sim

logger = logging.getLogger(__name__)
