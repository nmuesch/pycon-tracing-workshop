from __future__ import print_function

from flask import Flask, request, jsonify
from flask_sqlalchemy import  SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
db = SQLAlchemy(app)

class Beer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)

    def __init__(self, name):
        self.name = name

    def serialize(self):
        return {
            "id": self.id,
            "name": self.name
        }

class Donut(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)

    def __init__(self, name):
        self.name = name

    def serialize(self):
        return {
            "id": self.id,
            "name": self.name
        }

@app.route('/ping')
def ping():
    return "200 OK"

@app.route('/beers')
def beers():
    # Get beers from the database
    return jsonify(beers=[b.serialize() for b in Beer.query.all()])

@app.route('/donuts')
def donuts():
    # Get donuts from the database
    return jsonify(donuts=[d.serialize() for d in Donut.query.all()])

@app.route('/beer/<name>')
def beer(name):
    # Get beers from the database
    return jsonify(Beer.query.filter_by(name=name).first().serialize())

@app.route('/donut/<name>')
def donut(name):
    # Get donuts from the database
    return jsonify(Donut.query.filter_by(name=name).first().serialize())

@app.route('/pair/beer')
def pair():
    # Get beer name from params
    name = request.args.get('name')
    beers = Beer.query.filter_by(name=name)
    donuts = Donut.query.all()

    best_match(donuts, beer)
    return "200 OK"


def best_match(d, b):
    pass

if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True)
