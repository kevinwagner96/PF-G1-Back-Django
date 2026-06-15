from rest_framework.response import Response
from rest_framework.views import APIView

from demo.seed import reset_demo_state


class DemoResetView(APIView):
    def post(self, request):
        count = reset_demo_state()
        return Response({"status": "ok", "message": "Demo restablecida", "cirugias_restablecidas": count})
