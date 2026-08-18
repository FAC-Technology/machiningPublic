from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


@login_required
def home(request):
    if request.user.role == request.user.Role.MACHINIST:
        return redirect("jobs:queue")
    return redirect("jobs:engineer")
