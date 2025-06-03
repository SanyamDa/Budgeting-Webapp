// lib/firebase.js

import { initializeApp } from "firebase/app"
import { getAuth } from "firebase/auth"

// Your Firebase config (keep this secret)
const firebaseConfig = {
  apiKey: "AIzaSyBkPCoRqeUbHKWpIjb_2-9-U9v7xOGMYx4",
  authDomain: "financeapp-df2ca.firebaseapp.com",
  projectId: "financeapp-df2ca",
  storageBucket: "financeapp-df2ca.firebasestorage.app",
  messagingSenderId: "595246317935",
  appId: "1:595246317935:web:8fd414a7518775927ce89a"
}

// Initialize Firebase
const app = initializeApp(firebaseConfig)

// Export the auth module for login/logout
const auth = getAuth(app)
export { auth }