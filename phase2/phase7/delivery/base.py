from abc import ABC, abstractmethod

class DeliveryChannel(ABC):
    @abstractmethod
    def send_alert(self, assessment_context: dict, needs_review: bool = False) -> None: ...

    @abstractmethod
    def send_report(self, report_context: dict, pdf_path: str) -> None: ...