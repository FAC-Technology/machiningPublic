SESSION_KEY = "working_as_id"


def current_person(request):
    pk = request.session.get(SESSION_KEY)
    if not pk:
        return None
    from .models import Person

    return Person.objects.filter(pk=pk, is_active=True).first()


def set_current_person(request, person):
    if person:
        request.session[SESSION_KEY] = person.pk
    else:
        request.session.pop(SESSION_KEY, None)
