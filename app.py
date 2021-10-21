from flask import Flask, session, redirect, render_template, request, g
from flask_session import Session
import sqlite3
import stanza
import shlex
import time
import ast
import re

application = Flask(__name__)
application.secret_key = 'jGFoMdMX'
SESSION_TYPE = 'filesystem'
SESSION_PERMANENT = False
application.config.from_object(__name__)
Session(application)

nlp = stanza.Pipeline(lang='RU', processors='tokenize, pos, lemma')
con = sqlite3.connect("corpus.db", check_same_thread=False)
cur = con.cursor()


def queryParse(query):
    parsed = []
    cur.execute('SELECT DISTINCT pos FROM words')
    pos_list = [x[0] for x in cur.fetchall()]
    test = shlex.split(query, posix=False)
    for te in test:
        if te.lower() in pos_list:
            parsed.append((te.lower(), 'pos'))
        elif te[0] == '"' and te[-1] == '"':
            test = te.split(' ')
            for ele in test:
                ele = ele.replace('"', '')
                parsed.append((ele, 'token'))
        elif len(te.split('+')) > 1:
            le = te.split('+')
            stanza_tagged = []
            doc = nlp(le[0])
            for sent in doc.sentences:
                for word in sent.words:
                    stanza_tagged.append(word.lemma)
            parsed.append((stanza_tagged[0].lower(), 'lemma', le[1].lower()))
        else:
            stanza_tagged = []
            doc = nlp(te)
            for sent in doc.sentences:
                for word in sent.words:
                    stanza_tagged.append(word.lemma)
            parsed.append((stanza_tagged[0].lower(), 'lemma'))
    return parsed


@application.route('/')
def home():
    return render_template('index.html')


@application.before_request
def before_request():
    g.request_start_time = time.time()
    g.request_time = lambda: "%.5fs" % (time.time() - g.request_start_time)


@application.route('/process', methods=['GET'])
def main():
    try:
        QUERY = request.args.get('query')
    except AttributeError:
        return render_template('results.html', results='', query='', amount=0, time=g.request_time(), has_prev=False,
                               has_next=False, current_page=1, number_of_pages=0)

    if len(QUERY.strip()) == 0:
        return render_template('results.html', results='', query='', amount=0, time=g.request_time(), has_prev=False,
                               has_next=False, current_page=1, number_of_pages=0)

    try:
        parsed_query = queryParse(QUERY)
    except:
        return render_template('results.html', results='', query='', amount=0, time=g.request_time(), has_prev=False,
                               has_next=False, current_page=1, number_of_pages=0)

    cur.execute('SELECT result FROM cache WHERE query = ?', (str(parsed_query),))
    cached_res = cur.fetchone()
    if cached_res is not None:
        first_elements_list = ast.literal_eval(cached_res[0])
    else:
        SELECT = [('text, sentence, ' + ', '.join('t' + str(x) for x in range(1, len(parsed_query) + 1)))]
        FROM = []
        WHERE = []
        for num, element in enumerate(parsed_query, start=1):
            if num == 1:
                if len(element) == 3:
                    FROM.append((parsed_query[0][1] + ' AS col1, token AS t1, pos AS pos1, text, sentence'))
                    WHERE.append('(col' + str(num) + '=' + "'" + element[0].capitalize() + "'" + ' OR col' + str(num) + '=' + "'" + element[0] + "')" + ' AND (pos' + str(num) + ' = ' + "'" + element[2] + "')")
                else:
                    FROM.append((parsed_query[0][1] + ' AS col1, token AS t1, text, sentence'))
                    if element[1] == 'pos':
                        WHERE.append('(col' + str(num) + '=' + "'" + element[0] + "')")
                    else:
                        WHERE.append('(col' + str(num) + '=' + "'" + element[0].capitalize() + "'" + ' OR col' + str(num) + '=' + "'" +element[0] + "')")
            else:
                if len(element) == 3:
                    FROM.append(('LEAD(' + element[1] + ', ' + str(num - 1) + ') OVER (PARTITION BY text, sentence) AS col' + str(num)))
                    FROM.append(('LEAD(token, ' + str(num - 1) + ') OVER (PARTITION BY text, sentence) AS t' + str(num)))
                    FROM.append(('LEAD(pos, ' + str(num - 1) + ') OVER (PARTITION BY text, sentence) AS pos' + str(num)))
                    WHERE.append('(col' + str(num) + '=' + "'" + element[0].capitalize() + "'" + ' OR col' + str(num) + '=' + "'" + element[0] + "')" + ' AND (pos' + str(num) + ' = ' + "'" + element[2] + "')")
                else:
                    FROM.append(('LEAD(' + element[1] + ', ' + str(num - 1) + ') OVER (PARTITION BY text, sentence) AS col' + str(num)))
                    FROM.append(('LEAD(token, ' + str(num - 1) + ') OVER (PARTITION BY text, sentence) AS t' + str(num)))
                    if element[1] == 'pos':
                        WHERE.append('(col' + str(num) + '=' + "'" + element[0] + "')")
                    else:
                        WHERE.append('(col' + str(num) + '=' + "'" + element[0].capitalize() + "'" + ' OR col' + str(num) + '=' + "'" + element[0] + "')")

        SELECT = 'SELECT ' + ''.join(SELECT)
        FROM = ' FROM (SELECT ' + ', '.join(FROM) + ' FROM words)'
        WHERE = ' WHERE ' + ' AND '.join(WHERE)
        cur.execute(SELECT + FROM + WHERE)
        first_elements_list = cur.fetchall()
        if len(first_elements_list) < 100000:
            cur.execute('INSERT INTO cache VALUES (?, ?)', (str(parsed_query), str(first_elements_list)))
            con.commit()
    session['query'] = QUERY
    session['elements'] = first_elements_list
    session['query_len'] = len(parsed_query)
    session['time'] = g.request_time()
    return redirect('results')


@application.route('/results')
def returnResults():
    page_arg = int(request.args.get('page')) - 1 if request.args.get('page') is not None else 0
    page_number_arg = page_arg if page_arg is not None else 1

    first_elements_list = session.get('elements')
    try:
        elements_on_page = first_elements_list[(int(page_number_arg) * 10):(int(page_number_arg) * 10 + 10)]
    except TypeError:
        return render_template('results.html', results='', query='', amount=0, time=g.request_time(), has_prev=False,
                               has_next=False, current_page=1, number_of_pages=0)

    if len(first_elements_list) % 10 == 0:
        number_of_pages = int(len(first_elements_list) / 10)
    else:
        number_of_pages = int(len(first_elements_list) / 10) + 1

    has_prev_page = True if int(page_number_arg) > 0 else False
    has_next_page = True if int(page_number_arg) < number_of_pages - 1 else False

    output = []
    for lst in elements_on_page:
        cur.execute('SELECT token FROM words WHERE text = ? AND sentence = ?', (lst[0], lst[1]))
        sentence = ' '.join([x[0] for x in cur.fetchall()])
        sentence = re.sub(r'\s([?.!,:](?:\s|$))', r'\1', sentence)
        sentence = re.sub(r'"\s*([^"]*?)\s*"', r'"\1"', sentence)
        ngram = ' '.join(lst[2:])
        ngram = re.sub(r'\s([?.!,:](?:\s|$))', r'\1', ngram)
        ngram = re.sub(r'"\s*([^"]*?)\s*"', r'"\1"', ngram)
        cur.execute('SELECT title, date, source FROM texts WHERE id = ?', (lst[0],))
        res = cur.fetchone()
        meta = (res[0], res[1], res[2])
        output.append((sentence, ngram, meta))

    return render_template('results.html', results=output, query=session.get('query'), amount=len(first_elements_list),
                           time=session.get('time'), has_prev=has_prev_page, has_next=has_next_page,
                           current_page=page_number_arg, number_of_pages=number_of_pages)


if __name__ == '__main__':
    application.run(threaded=True)
