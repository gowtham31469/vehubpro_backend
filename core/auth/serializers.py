from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.common.encryption.pii import encryptor
from apps.platform.users.models import UserPII

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        email = attrs.get("email", "").strip().lower()
        password = attrs.get("password")

        email_hash = encryptor.hash_value(email)
        pii = (
            UserPII.objects.select_related("user")
            .filter(email_hash=email_hash, is_anonymized=False)
            .first()
        )
        if not pii or not pii.user:
            raise serializers.ValidationError("Invalid email or password.")

        user = pii.user
        if not user.check_password(password):
            raise serializers.ValidationError("Invalid email or password.")
        if not user.is_active:
            raise serializers.ValidationError("User account is inactive.")

        attrs["user"] = user
        attrs["email"] = email
        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
