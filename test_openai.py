#!/usr/bin/env python3
"""
Test script to diagnose OpenAI API issues
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_openai_connection():
    """Test basic OpenAI API connection"""
    try:
        print("Testing OpenAI API connection...")
        
        # Check if API key is loaded
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            print("❌ ERROR: OPENAI_API_KEY not found in environment variables")
            return False
        
        print(f"✅ API key found: {api_key[:10]}...{api_key[-4:]}")
        
        # Try importing OpenAI
        try:
            from openai import OpenAI
            print("✅ OpenAI library imported successfully")
        except ImportError as e:
            print(f"❌ ERROR: Failed to import OpenAI library: {e}")
            return False
        
        # Try creating client
        try:
            client = OpenAI(api_key=api_key)
            print("✅ OpenAI client created successfully")
        except Exception as e:
            print(f"❌ ERROR: Failed to create OpenAI client: {e}")
            return False
        
        # Try a simple API call (text only, no vision)
        try:
            print("Testing basic API call...")
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "Say hello"}],
                max_tokens=10
            )
            print(f"✅ Basic API call successful: {response.choices[0].message.content}")
        except Exception as e:
            print(f"❌ ERROR: Basic API call failed: {e}")
            return False
        
        print("✅ All tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        return False

if __name__ == "__main__":
    test_openai_connection()
