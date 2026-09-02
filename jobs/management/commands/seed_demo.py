from django.core.management.base import BaseCommand

from jobs.models import Destination, Panel, Person, Project


class Command(BaseCommand):
    help = "Create shop people and material panels. Does not create jobs."

    def handle(self, *args, **options):
        people = [
            ("Hasan", "HA", True, True, True),
        ]
        for name, initials, engineer, machinist, admin in people:
            person, created = Person.objects.get_or_create(
                initials=initials,
                defaults={
                    "name": name,
                    "is_engineer": engineer,
                    "is_machinist": machinist,
                    "is_admin": admin,
                },
            )
            if not created:
                person.name = name
                person.is_engineer = engineer
                person.is_machinist = machinist
                person.is_admin = admin
                person.save()

        for panel_name in [
            "18mm birch ply",
            "12mm MDF",
            "6mm 6082 aluminium",
            "3mm acrylic",
        ]:
            Panel.objects.get_or_create(name=panel_name)

        for project_name in ["PRD", "P10", "P05", "R&D"]:
            Project.objects.get_or_create(name=project_name)

        for destination_name in ["Unit 1", "Unit 2", "Unit 4"]:
            Destination.objects.get_or_create(name=destination_name)

        self.stdout.write(self.style.SUCCESS("People, panels, projects, and destinations ready. Add the rest of the shop on /setup/."))
        self.stdout.write("On Submit job, drag in a PDF, DXF, and VCarve file.")
