"""
Views for homepage and landing page
"""
from django.shortcuts import render
from django.http import JsonResponse

def home(request):
    """Render the main landing page"""
    return render(request, 'home/index.html')

def health_check(request):
    """Health check endpoint for Render deployment monitoring"""
    return JsonResponse({'status': 'healthy', 'service': 'CryptoSight'}, status=200)
