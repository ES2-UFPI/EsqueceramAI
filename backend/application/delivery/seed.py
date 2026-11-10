"""Matrícula da conta de demonstração do atendente (para o checkout funcionar logo no primeiro uso)."""
from application.delivery import repository as repo
from application.repositories.users import find_user_by_email

DEMO_EMAIL = "operador@ufpi.edu.br"
DEMO_REGISTRATION = "ATD-2024-0117"


def ensure_demo_attendant() -> None:
    """Idempotente: nunca sobrescreve uma matrícula já cadastrada."""
    user = find_user_by_email(DEMO_EMAIL)
    if user and user.role == "OPERATOR_POST" and not repo.get_registration(user.id):
        try:
            repo.set_registration(user.id, DEMO_REGISTRATION)
        except repo.RegistrationTaken:
            pass
