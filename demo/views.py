from django.conf import settings
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from demo.seed import reset_demo_state
from plannings.agenda import is_admin


class DemoResetView(APIView):
    def post(self, request):
        if not settings.DEMO_RESET_ENABLED:
            raise NotFound()
        if not is_admin(request.user):
            raise PermissionDenied()
        count = reset_demo_state()
        return Response({"status": "ok", "message": "Demo restablecida", "cirugias_restablecidas": count})
