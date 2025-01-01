from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Create Fake Data"

    def handle(self, *args, **kwargs):
        print("Read to Create Fake Data !")