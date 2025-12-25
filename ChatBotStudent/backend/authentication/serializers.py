from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import Faculty, PasswordResetToken


class LoginSerializer(serializers.Serializer):
    """
    Serializer cho đăng nhập
    """
    faculty_code = serializers.CharField(
        max_length=20,
        help_text="Mã giảng viên"
    )
    password = serializers.CharField(
        write_only=True,
        help_text="Mật khẩu"
    )
    remember_me = serializers.BooleanField(
        default=False,
        help_text="Ghi nhớ đăng nhập"
    )
    
    def validate(self, attrs):
        faculty_code = attrs.get('faculty_code')
        password = attrs.get('password')
        
        if not faculty_code or not password:
            raise serializers.ValidationError("Vui lòng nhập đầy đủ mã giảng viên và mật khẩu")
        
        # Chuẩn hóa mã giảng viên
        faculty_code = faculty_code.strip().upper()
        attrs['faculty_code'] = faculty_code
        
        return attrs


class FacultyProfileSerializer(serializers.ModelSerializer):
    """
    Serializer cho thông tin profile giảng viên
    """
    class Meta:
        model = Faculty
        fields = [
            'id', 'faculty_code', 'full_name', 'email', 'gender',  
            'department', 'phone', 'is_active_faculty',
            'last_login', 'date_joined'
        ]
        read_only_fields = ['id', 'faculty_code', 'last_login', 'date_joined']


class PasswordResetRequestSerializer(serializers.Serializer):
    """
    Serializer cho yêu cầu reset password
    """
    faculty_code = serializers.CharField(
        max_length=20,
        help_text="Mã giảng viên"
    )
    email = serializers.EmailField(
        help_text="Email đăng ký"
    )
    
    def validate(self, attrs):
        faculty_code = attrs.get('faculty_code', '').strip().upper()
        email = attrs.get('email', '').strip().lower()
        
        attrs['faculty_code'] = faculty_code
        attrs['email'] = email
        
        return attrs


class PasswordResetConfirmSerializer(serializers.Serializer):
    """
    Serializer cho xác nhận reset password
    """
    token = serializers.UUIDField(help_text="Token reset password")
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
        help_text="Mật khẩu mới (tối thiểu 8 ký tự)"
    )
    confirm_password = serializers.CharField(
        write_only=True,
        help_text="Xác nhận mật khẩu mới"
    )
    
    def validate(self, attrs):
        new_password = attrs.get('new_password')
        confirm_password = attrs.get('confirm_password')
        
        if new_password != confirm_password:
            raise serializers.ValidationError("Mật khẩu xác nhận không khớp")
        
        # Validate password strength
        try:
            validate_password(new_password)
        except ValidationError as e:
            raise serializers.ValidationError(f"Mật khẩu không đủ mạnh: {', '.join(e.messages)}")
        
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializer cho đổi mật khẩu khi đã đăng nhập
    """
    current_password = serializers.CharField(
        write_only=True,
        help_text="Mật khẩu hiện tại"
    )
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
        help_text="Mật khẩu mới"
    )
    confirm_password = serializers.CharField(
        write_only=True,
        help_text="Xác nhận mật khẩu mới"
    )
    
    def validate(self, attrs):
        new_password = attrs.get('new_password')
        confirm_password = attrs.get('confirm_password')
        
        if new_password != confirm_password:
            raise serializers.ValidationError("Mật khẩu xác nhận không khớp")
        
        try:
            validate_password(new_password)
        except ValidationError as e:
            raise serializers.ValidationError(f"Mật khẩu không đủ mạnh: {', '.join(e.messages)}")
        
        return attrs