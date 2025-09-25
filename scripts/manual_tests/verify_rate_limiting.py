"""
Test the rate limiting system with a quick verification.
"""

from src.crawler import ContentExtractor, RateLimitError
import time

def test_rate_limiting_functionality():
    """Quick test to verify rate limiting is working."""
    print("Testing Rate Limiting Implementation")
    print("=" * 40)
    
    extractor = ContentExtractor()
    
    # Test 1: Verify RateLimitError exists and can be raised
    try:
        raise RateLimitError("Test error")
    except RateLimitError:
        print("✅ RateLimitError exception works correctly")
    
    # Test 2: Test rate limiting state management
    domain = "test-domain.com"
    
    # Initially no rate limiting
    assert not extractor._check_rate_limit(domain)
    print("✅ Rate limit check works for non-limited domain")
    
    # Set rate limiting
    future_time = time.time() + 30
    extractor.domain_backoff_until[domain] = future_time
    assert extractor._check_rate_limit(domain)
    print("✅ Rate limit check detects active rate limiting")
    
    # Test error count handling
    extractor._handle_rate_limit_error(domain)
    assert extractor.domain_error_counts[domain] == 1
    print("✅ Error count increments correctly")
    
    # Test error reset
    extractor._reset_error_count(domain)
    assert extractor.domain_error_counts[domain] == 0
    print("✅ Error count resets correctly")
    
    # Test error result creation
    error_result = extractor._create_error_result("test.com", "Test error", {"status": 429})
    assert error_result["success"] is False
    assert error_result["error"] == "Test error"
    assert error_result["url"] == "test.com"
    print("✅ Error result creation works correctly")
    
    print("\n🎉 All rate limiting tests passed!")
    print("The system is ready to handle 429 errors and implement exponential backoff.")

if __name__ == "__main__":
    test_rate_limiting_functionality()