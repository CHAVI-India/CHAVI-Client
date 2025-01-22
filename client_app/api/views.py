from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.views import APIView

from client_app.models import *
from client_app.api.serializers import *


@api_view(['GET',])
def get_stage_information(request):
    try:
        stage_information = StageInformation.objects.all()
        serializer = StageInformationSerializer(stage_information, many=True)
        return Response(serializer.data)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
