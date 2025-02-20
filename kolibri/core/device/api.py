from datetime import timedelta
from sys import version_info

from django.conf import settings
from django.db.models import Exists
from django.db.models import Max
from django.db.models import OuterRef
from django.db.models.query import Q
from django.http.response import HttpResponseBadRequest
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from django_filters.rest_framework import FilterSet
from django_filters.rest_framework import ModelChoiceFilter
from morango.models import InstanceIDModel
from morango.models import TransferSession
from rest_framework import mixins
from rest_framework import status
from rest_framework import views
from rest_framework import viewsets
from rest_framework.response import Response

import kolibri
from .models import DevicePermissions
from .models import DeviceSettings
from .models import UserSyncStatus
from .permissions import NotProvisionedCanPost
from .permissions import UserHasAnyDevicePermissions
from .serializers import DevicePermissionsSerializer
from .serializers import DeviceProvisionSerializer
from .serializers import DeviceSettingsSerializer
from kolibri.core.api import ReadOnlyValuesViewset
from kolibri.core.auth.api import KolibriAuthPermissions
from kolibri.core.auth.api import KolibriAuthPermissionsFilter
from kolibri.core.auth.models import Collection
from kolibri.core.content.permissions import CanManageContent
from kolibri.core.device.utils import get_device_setting
from kolibri.core.discovery.models import DynamicNetworkLocation
from kolibri.utils.conf import OPTIONS
from kolibri.utils.server import get_urls
from kolibri.utils.server import installation_type
from kolibri.utils.system import get_free_space
from kolibri.utils.time_utils import local_now


class DevicePermissionsViewSet(viewsets.ModelViewSet):
    queryset = DevicePermissions.objects.all()
    serializer_class = DevicePermissionsSerializer
    permission_classes = (KolibriAuthPermissions,)
    filter_backends = (KolibriAuthPermissionsFilter,)


class DeviceProvisionView(viewsets.GenericViewSet):
    permission_classes = (NotProvisionedCanPost,)
    serializer_class = DeviceProvisionSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.save()
        output_serializer = self.get_serializer(data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


class FreeSpaceView(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = (CanManageContent,)

    def list(self, request):
        path = request.query_params.get("path")
        if path is None:
            free = get_free_space()
        elif path == "Content":
            free = get_free_space(OPTIONS["Paths"]["CONTENT_DIR"])
        else:
            free = get_free_space(path)

        return Response({"freespace": free})


class DeviceInfoView(views.APIView):

    permission_classes = (UserHasAnyDevicePermissions,)

    def get(self, request, format=None):
        info = {}

        info["version"] = kolibri.__version__

        status, urls = get_urls()
        if not urls:
            # Will not return anything when running the debug server, so at least return the current URL
            urls = [
                request.build_absolute_uri(OPTIONS["Deployment"]["URL_PATH_PREFIX"])
            ]

        filtered_urls = [
            url for url in urls if "127.0.0.1" not in url and "localhost" not in url
        ]

        if filtered_urls:
            urls = filtered_urls

        info["urls"] = urls

        db_engine = settings.DATABASES["default"]["ENGINE"]

        if db_engine.endswith("sqlite3"):
            # Return path to .sqlite file (usually in KOLIBRI_HOME folder)
            info["database_path"] = settings.DATABASES["default"]["NAME"]
        elif db_engine.endswith("postgresql"):
            info["database_path"] = "postgresql"
        else:
            info["database_path"] = "unknown"

        instance_model = InstanceIDModel.get_or_create_current_instance()[0]

        info["device_id"] = instance_model.id
        info["os"] = instance_model.platform

        info["content_storage_free_space"] = get_free_space(
            OPTIONS["Paths"]["CONTENT_DIR"]
        )

        # This returns the localized time for the server
        info["server_time"] = local_now()
        # Returns the named timezone for the server (the time above only includes the offset)
        info["server_timezone"] = settings.TIME_ZONE
        info["installer"] = installation_type()
        info["python_version"] = "{major}.{minor}.{micro}".format(
            major=version_info.major, minor=version_info.minor, micro=version_info.micro
        )

        if not request.user.is_superuser:
            # If user is not superuser, return just free space available and kolibri version
            keys_to_remove = [
                "urls",
                "database_path",
                "device_id",
                "os",
                "server_time",
                "server_timezone",
                "installer",
                "python_version",
            ]
            for key in keys_to_remove:
                del info[key]

        return Response(info)


class DeviceSettingsView(views.APIView):

    permission_classes = (UserHasAnyDevicePermissions,)

    def get(self, request):
        settings = DeviceSettings.objects.get()
        return Response(DeviceSettingsSerializer(settings).data)

    def patch(self, request):
        settings = DeviceSettings.objects.get()

        serializer = DeviceSettingsSerializer(settings, data=request.data)

        if not serializer.is_valid():
            return HttpResponseBadRequest(serializer.errors)

        serializer.save()
        return Response(serializer.data)


class DeviceNameView(views.APIView):
    permission_classes = (UserHasAnyDevicePermissions,)

    def get(self, request):
        settings = DeviceSettings.objects.get()
        return Response({"name": settings.name})

    def patch(self, request):
        settings = DeviceSettings.objects.get()
        settings.name = request.data["name"]
        settings.save()
        return Response({"name": settings.name})


class SyncStatusFilter(FilterSet):

    member_of = ModelChoiceFilter(
        method="filter_member_of", queryset=Collection.objects.all()
    )

    def filter_member_of(self, queryset, name, value):
        return queryset.filter(
            Q(user__memberships__collection=value) | Q(user__facility=value)
        )

    class Meta:
        model = UserSyncStatus
        fields = ["user", "member_of"]


RECENTLY_SYNCED = "RECENTLY_SYNCED"
SYNCING = "SYNCING"
QUEUED = "QUEUED"
NOT_RECENTLY_SYNCED = "NOT_RECENTLY_SYNCED"


def map_status(status):
    """
    Summarize the current state of the sync into a constant for use by
    the frontend.
    """
    if status["active"]:
        return SYNCING
    elif status["queued"]:
        return QUEUED
    elif status["last_synced"]:
        # Keep this as a fixed constant for now.
        # In future versions this may be configurable.
        if timezone.now() - status["last_synced"] < timedelta(minutes=15):
            return RECENTLY_SYNCED
        else:
            return NOT_RECENTLY_SYNCED


class UserSyncStatusViewSet(ReadOnlyValuesViewset):
    permission_classes = (KolibriAuthPermissions,)
    filter_backends = (KolibriAuthPermissionsFilter, DjangoFilterBackend)
    queryset = UserSyncStatus.objects.all()
    filter_class = SyncStatusFilter

    values = (
        "queued",
        "last_synced",
        "active",
        "user",
    )

    field_map = {
        "status": map_status,
    }

    def get_queryset(self):
        # If this is a subset of users device, we should just return no data
        # if there are no possible devices we could sync to.
        if (
            get_device_setting("subset_of_users_device", False)
            and not DynamicNetworkLocation.objects.filter(
                subset_of_users_device=False
            ).exists()
        ):
            return UserSyncStatus.objects.none()
        return UserSyncStatus.objects.all()

    def annotate_queryset(self, queryset):

        queryset = queryset.annotate(
            last_synced=Max("sync_session__last_activity_timestamp")
        )

        active_transfer_sessions = TransferSession.objects.filter(
            sync_session=OuterRef("sync_session"), active=True
        )

        queryset = queryset.annotate(active=Exists(active_transfer_sessions))

        return queryset
