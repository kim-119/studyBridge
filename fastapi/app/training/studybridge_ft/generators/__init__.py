from .concept import ConceptGenerator
from .archive_qa import ArchiveQAGenerator
from .quiz import QuizGenerator
from .socratic import SocraticGenerator
from .debate import DebateGenerator
from .professor import ProfessorGenerator
from .format_safety import FormatSafetyGenerator

REGISTRY = {
    "concept": ConceptGenerator, "archive_qa": ArchiveQAGenerator,
    "quiz": QuizGenerator, "socratic": SocraticGenerator,
    "debate": DebateGenerator, "professor": ProfessorGenerator,
    "format_safety": FormatSafetyGenerator,
}
