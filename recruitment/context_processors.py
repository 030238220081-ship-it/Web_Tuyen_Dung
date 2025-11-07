from .models import Notification, DirectMessage

def notifications_context(request):
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return {'unread_notifications_count': unread_count}
    return {}

def notifications_context(request):
    if request.user.is_authenticated:
        unread_notifications_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        unread_messages_count = DirectMessage.objects.filter(recipient=request.user, is_read=False).count()
        
        return {
            'unread_notifications_count': unread_notifications_count,
            'unread_messages_count': unread_messages_count 
        }
    return {}