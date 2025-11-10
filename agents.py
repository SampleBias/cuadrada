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
    - Be generous in scoring - when in doubt, round up not down

    The reviewer will calculate the weighted final score based on the criteria weights.
    
    Recommendation threshold (more lenient standards):
    - Accept (>60%): Good paper that contributes to the field
    - Accept with Minor Revision (50-60%): Promising work needing minor improvements
    - Accept with Major Revision (40-50%): Valuable contribution requiring significant changes
    - Reject (<40%): Does not meet basic publication standards

    IMPORTANT: The conference values inclusivity and diverse perspectives. Papers should generally 
    be accepted unless there are serious, unfixable flaws. Even papers with methodology issues 
    should be accepted if they present interesting ideas or perspectives. The default stance 
    should be acceptance rather than rejection.

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
        "claude-3-5-sonnet-20241022",  # Latest and most capable
        "claude-3-5-sonnet-20240620",  # Previous version
        "claude-3-haiku-20240307",     # Faster but less capable
        "claude-3-opus-20240229",      # Fallback model
    ]

    def __init__(self, model_index=0):  # Default to latest sonnet (index 0)
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
        
        # Validate input
        if not paper_text or len(paper_text.strip()) < 100:
            raise ValueError("Paper text is too short or empty. Please ensure you uploaded a valid research paper.")
        
        print(f"Generating review with model {self.current_model} (paper length: {len(paper_text)} chars)")
        
        while retry_count < max_retries:
            try:
                response = self.client.messages.create(
                    model=self.current_model,
                    max_tokens=4000,
                    system=self.REVIEW_PROMPT,
                    messages=[{"role": "user", "content": paper_text}]
                )
                print(f"Successfully generated review with model {self.current_model}")
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
            
            except anthropic.AuthenticationError as e:
                print(f"Authentication error with model {self.current_model}: {str(e)}")
                raise Exception(f"API authentication failed. Please check your API key configuration. Error: {str(e)}")
            
            except anthropic.BadRequestError as e:
                print(f"Bad request error with model {self.current_model}: {str(e)}")
                raise Exception(f"Invalid request to AI service. This might be due to content length or format issues. Error: {str(e)}")
            
            except anthropic.APIError as e:
                print(f"API error with model {self.current_model}: {str(e)}")
                # For general API errors, retry with backoff
                retry_count += 1
                if retry_count < max_retries:
                    print(f"Retrying after API error. Attempt {retry_count}/{max_retries}")
                    time.sleep(backoff_time)
                    backoff_time *= 2
                else:
                    raise Exception(f"AI service encountered an error after {max_retries} attempts. Error: {str(e)}")
        
        # If we get here, all retries have been exhausted
        raise Exception("Our AI review system is experiencing high demand. We tried multiple models but couldn't complete your review. Please try again in a few minutes.")

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from PDF file"""
        try:
            print(f"Extracting text from PDF: {pdf_path}")
            
            if not os.path.exists(pdf_path):
                raise FileNotFoundError(f"PDF file not found at path: {pdf_path}")
            
            doc = fitz.open(pdf_path)
            text = ""
            page_count = len(doc)
            print(f"PDF has {page_count} pages")
            
            for page_num, page in enumerate(doc, 1):
                page_text = page.get_text()
                text += page_text
                print(f"Extracted {len(page_text)} chars from page {page_num}/{page_count}")
            
            doc.close()
            
            if not text or len(text.strip()) < 100:
                raise ValueError(f"PDF appears to be empty or contains insufficient text (extracted {len(text)} chars). Please ensure the PDF contains readable text.")
            
            print(f"Successfully extracted {len(text)} total characters from PDF")
            return text
            
        except Exception as e:
            print(f"Error extracting text from PDF: {str(e)}")
            raise

    def analyze_paper(self, input_path: str) -> str:
        """Analyze paper and return review text"""
        try:
            paper_text = self.extract_text_from_pdf(input_path)
            review = self.generate_review(paper_text)
            return review
        except Exception as e:
            print(f"Error analyzing paper at {input_path}: {str(e)}")
            raise

class ClaudeAgent(BaseReviewer):
    """Claude-based reviewer with built-in fallback to less capable models"""
    def __init__(self, model_index=0):  # Default to latest sonnet (index 0)
        super().__init__(model_index)
        print(f"Initialized ClaudeAgent with model: {self.current_model}") 