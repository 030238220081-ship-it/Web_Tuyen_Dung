from .models import Notification

def notifications_context(request):
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return {'unread_notifications_count': unread_count}
    return {}