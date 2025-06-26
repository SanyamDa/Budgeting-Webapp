from website import create_app

app = create_app()

if __name__ == '__main__': # if we run this file through main.py, then only will it work 
    app.run(debug = True) #run a flask application and start the web server


