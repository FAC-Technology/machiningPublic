from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ENGINEER = "engineer", "Engineer"
        MACHINIST = "machinist", "Machinist"
        ADMIN = "admin", "Admin"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ENGINEER)
    display_name = models.CharField(max_length=120, blank=True)

    @property
    def label(self):
        return self.display_name or self.get_full_name() or self.username

    def is_engineer_role(self):
        return self.role in (self.Role.ENGINEER, self.Role.ADMIN)

    def is_machinist_role(self):
        return self.role in (self.Role.MACHINIST, self.Role.ADMIN)
