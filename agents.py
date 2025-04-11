from abc import ABC, abstractmethod
import os
import fitz  # PyMuPDF
from dotenv import load_dotenv
import anthropic
import time

load_dotenv()

class BaseReviewer(ABC):
    """Base class for all reviewer agents with standardized review criteria"""
    
    REVIEW_PROMPT = """
    You are an academic reviewer evaluating a research paper. Write your review in third person, 
    starting with "The reviewer has evaluated this paper based on the given criteria and arrived 
    at the following conclusions:"

    Evaluate each criterion from 0-100%:

    1. Methodology (20% of total): Evaluate the research methodology, experimental design, and validation
    2. Novelty (20% of total): Assess the innovation and original contribution to the field
    3. Technical Depth (15% of total): Examine technical accuracy, depth of analysis, and rigor
    4. Clarity (15% of total): Evaluate writing quality, organization, and presentation
    5. Literature Review (15% of total): Assess coverage and understanding of related work
    6. Impact (15% of total): Consider potential influence on the field and practical applications

    For each criterion, the reviewer should:
    - Begin with positive aspects before addressing issues
    - Provide constructive suggestions for improvement
    - Assign a percentage score (aim to be generous in assessment)
    - Highlight strengths more prominently than weaknesses

    The reviewer will calculate the weighted final score based on the criteria weights.
    
    Recommendation threshold (more lenient standards):
    - Accept (>70%): Good paper that contributes to the field
    - Accept with Minor Revision (60-70%): Promising work needing minor improvements
    - Accept with Major Revision (50-60%): Valuable contribution requiring significant changes
    - Reject (<50%): Does not meet basic publication standards

    The reviewer should adopt a supportive stance, looking for reasons to accept rather than reject, 
    recognizing the value of diverse contributions to academic discourse. Give authors the benefit 
    of the doubt when evaluating unclear aspects.

    The review concludes with:
    1. Final weighted score
    2. Summary of major strengths first, then minor weaknesses
    3. Constructive suggestions for improvement
    4. End with one of these exact phrases on a new line:
       - "FINAL DECISION: **ACCEPTED**"
       - "FINAL DECISION: **ACCEPTED WITH MINOR REVISION REQUIRED**"
       - "FINAL DECISION: **ACCEPTED WITH MAJOR REVISION REQUIRED**"
       - "FINAL DECISION: **REJECTED**"

    Always maintain third-person perspective throughout the review, using phrases like 
    "the reviewer notes", "the reviewer finds", "in the reviewer's assessment", etc.
    """

    # Available Claude models ordered by capability (highest to lowest)
    CLAUDE_MODELS = [
        "claude-3-opus-20240229",  # Most capable but more expensive
        "claude-3-sonnet-20240229", # Default model
        "claude-3-haiku-20240307",  # Faster but less capable
        "claude-2.1",               # Fallback to older model
    ]

    def __init__(self, model_index=1):  # Default to sonnet (index 1)
        self.setup_credentials()
        self.model_index = model_index
        self.current_model = self.CLAUDE_MODELS[model_index]
        
    def setup_credentials(self):
        """Setup Claude API credentials"""
        api_key = os.getenv('CLAUDE_API_KEY')
        if not api_key:
            raise ValueError("CLAUDE_API_KEY not found in environment variables")
        if not api_key.startswith('sk-ant-'):
            raise ValueError("Invalid Claude API key format. Should start with 'sk-ant-'")
        print(f"API key prefix: {api_key[:15]}...") # Debug - only shows prefix
        self.client = anthropic.Anthropic(api_key=api_key)

    def generate_review(self, paper_text: str) -> str:
        """Generate review using Claude with fallback to less capable models on rate limit"""
        max_retries = 3
        retry_count = 0
        backoff_time = 2  # Initial backoff time in seconds
        
        while retry_count < max_retries:
            try:
                response = self.client.messages.create(
                    model=self.current_model,
                    max_tokens=4000,
                    system=self.REVIEW_PROMPT,
                    messages=[{"role": "user", "content": paper_text}]
                )
                return response.content[0].text
                
            except anthropic.RateLimitError as e:
                print(f"Rate limit error with model {self.current_model}: {str(e)}")
                
                # Try to use a less capable model
                if self.model_index < len(self.CLAUDE_MODELS) - 1:
                    self.model_index += 1
                    self.current_model = self.CLAUDE_MODELS[self.model_index]
                    print(f"Downgrading to alternative model: {self.current_model}")
                    # Reset retry count since we're trying a new model
                    retry_count = 0
                else:
                    # No more models to try, wait and retry the last model
                    retry_count += 1
                    print(f"No more models available. Retrying {self.current_model} after backoff. Attempt {retry_count}/{max_retries}")
                    time.sleep(backoff_time)
                    backoff_time *= 2  # Exponential backoff
        
        # If we get here, all retries have been exhausted
        raise Exception("Review limit reached for your current plan. The system attempted to use multiple models but was unable to complete your request due to rate limiting.")

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from PDF file"""
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        return text

    def analyze_paper(self, input_path: str) -> str:
        """Analyze paper and return review text"""
        paper_text = self.extract_text_from_pdf(input_path)
        review = self.generate_review(paper_text)
        return review

class ClaudeAgent(BaseReviewer):
    """Claude-based reviewer with built-in fallback to less capable models"""
    def __init__(self, model_index=1):  # Default to sonnet (index 1)
        super().__init__(model_index)
        print(f"Initialized ClaudeAgent with model: {self.current_model}") 