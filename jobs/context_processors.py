from .identity import current_person
from .models import Person


def nav_extras(request):
    person = current_person(request)
    show_submit = person is None or person.is_engineer or person.is_admin
    return {
        "current_person": person,
        "all_people": Person.objects.filter(is_active=True),
        "show_submit": show_submit,
    }
