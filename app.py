from tokenize import group

from flask import Flask, render_template, request, redirect, url_for, session, flash, get_flashed_messages
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import statistics

from sqlalchemy.orm import joinedload
from flask_caching import Cache
from sqlalchemy.orm.attributes import flag_modified

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# MySQL configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:MySQL@localhost/sport_app'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300

cache = Cache(app)
# Database Models
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name_ = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_ = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    behavior = db.Column(db.Float, nullable=True)
    level_ = db.Column(db.Float, nullable=True)  # Average level from reviews
    is_admin = db.Column(db.Boolean, default=False)  # Admin role

class Facility(db.Model):
    __tablename__ = 'facility'
    id = db.Column(db.Integer, primary_key=True)
    name_ = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    sports = db.Column(db.String(255), nullable=False)

class Group(db.Model):
    __tablename__ = 'group_'
    id = db.Column(db.Integer, primary_key=True)
    name_ = db.Column(db.String(100), nullable=False)
    sport = db.Column(db.String(50), nullable=False)
    description_ = db.Column(db.Text, nullable=False)
    max_participants = db.Column(db.Integer, nullable=False)
    current_participants = db.Column(db.Integer, default=0)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=False)
    date_ = db.Column(db.Date, nullable=False)  # Updated
    time_ = db.Column(db.Time, nullable=False)  # Updated
    price = db.Column(db.Float, nullable=False)
    duration = db.Column(db.Integer, nullable=False)

    facility = db.relationship('Facility', backref='groups')


class GroupParticipants(db.Model):
    __tablename__ = 'group_participants'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group_.id'), nullable=False)
    db.UniqueConstraint('user_id', 'group_id', name='unique_user_group')

class Review(db.Model):
    __tablename__ = 'review'
    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reviewed_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating_skill = db.Column(db.Integer, nullable=False)
    rating_behavior = db.Column(db.Integer, nullable=False)
    comment_ = db.Column(db.Text)

class Sport(db.Model):
    __tablename__ = 'sports'
    id = db.Column(db.Integer, primary_key=True)
    name_ = db.Column(db.String(100), unique=True, nullable=False)


class UserProxy:
    def __init__(self, db_session, cache):
        self.db_session = db_session
        self.cache = cache

    def get_user_by_id(self, user_id, refresh_cache=False):
        return User.query.get(user_id)

    def is_admin(self, user_id):
            user = self.get_user_by_id(user_id)
            return user and user.is_admin

    def delete_user(self, user_to_ban):
        cache.delete(f"user_{user_to_ban.id}")
        cache.delete("users_ordered_by_behavior")
        cache.delete(f"user_email_{user_to_ban.email}")
        db.session.delete(user_to_ban)
        db.session.commit()

    def update_user_levels(self, user_id):

        user = self.get_user_by_id(user_id)
        if not user:
            print(f"[ERROR] User with ID {user_id} not found.")
            return

        reviews = Review.query.filter_by(reviewed_id=user_id).all()

        if reviews:
            avg_behavior = sum(review.rating_behavior for review in reviews) / len(reviews)
            avg_skill = sum(review.rating_skill for review in reviews) / len(reviews)
            user.behavior = round(avg_behavior, 2)
            user.level_ = round(avg_skill, 2)
        else:
            user.behavior = None
            user.level_ = None
        try:
            db.session.commit()
            print(f"[DEBUG] Updated user {user_id}: behavior={user.behavior}, skill={user.level_}")
        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Failed to update user {user_id}: {e}")

    def add_user(self, new_user):
        self.db_session.add(new_user)
        self.db_session.commit()
        self.cache.set(f"user_{new_user.id}", new_user)

    def get_user_by_email(self, email):
        cache_key = f"user_email_{email}"
        user = self.cache.get(cache_key)
        if not user:
            user = User.query.filter_by(email=email).first()
            self.cache.set(cache_key, user)
        return user


    def get_users_ordered_by_behavior(self):
        cache_key = "users_ordered_by_behavior"
        users = self.cache.get(cache_key)
        if not users:
            users = User.query.order_by(
                db.case((User.behavior == None, 1), else_=0),  # Move NULLs to the end
                User.behavior.asc()  # Sort by behavior descending
            ).all()
            self.cache.set(cache_key, users)
        return users


class GroupProxy:
    def __init__(self, db_session, cache):
        self.db_session = db_session
        self.cache = cache

    def get_group_by_id(self, group_id):

        cache_key = f"group_{group_id}"
        group = self.cache.get(cache_key)
        #if not group:
        group = Group.query.get(group_id)
        self.cache.set(cache_key, group)
        return group

    def add_group(self, group_data):

        self.db_session.add(group_data)
        self.db_session.commit()
        self.cache.set(f"group_{group_data.id}", group)
        return group

    def delete_group(self, group_id):
        group = self.get_group_by_id(group_id)
        if group:
            GroupParticipants.query.filter_by(group_id=group_id).delete()
            self.db_session.delete(group)
            self.db_session.commit()
            self.cache.delete(f"group_{group_id}")

    def add_participant(self, user_id, group_id):
        participant = GroupParticipants(user_id=user_id, group_id=group_id)
        group = group_proxy.get_group_by_id(group_id)
        group.current_participants += 1
        db.session.add(participant)
        db.session.commit()
        self.cache.set(f"group_{group_id}", group)

    def remove_participant(self,participant):
        self.cache.delete(f"groups_user_{participant.group_id}")
        self.db_session.delete(participant)
        self.db_session.commit()

    def get_filtered_groups(self, sport_filter=None, date_filter=None, facility_filter=None):

        query = Group.query.filter(
            Group.date_ >= date.today(),  # Only future groups
            Group.current_participants < Group.max_participants  # Only groups with available spots
        )

        if sport_filter:
            query = query.filter(Group.sport == sport_filter)
        if date_filter:
            query = query.filter(Group.date_ == date_filter)
        if facility_filter:
            query = query.filter(Group.facility_id == int(facility_filter))

        groups = query.all()
        return groups

    def check_participant_exists(self, user_id, group_id):
        existing_participant = GroupParticipants.query.filter_by(user_id=user_id, group_id=group_id).first()

        return existing_participant

    def get_group_participants(self, group_id):
        participants = GroupParticipants.query.filter_by(group_id=group_id).all()
        return participants

    def get_groups_by_participant(self, user_id):
        joined_groups  = (
            Group.query.options(joinedload(Group.facility))
            .join(GroupParticipants, Group.id == GroupParticipants.group_id)
            .filter(GroupParticipants.user_id == user_id)
            .all()
        )
        admin_groups = Group.query.filter_by(admin_id=user_id).all()
        all_groups = list(set(joined_groups + admin_groups))


        return all_groups


    def get_active_groups_by_participant(self, user_id):
        cache_key = f"active_groups_user_{user_id}"
        today = datetime.now()
        joined_groups = db.session.query(Group).join(GroupParticipants).filter(
            GroupParticipants.user_id == user_id,
            Group.date_ >= today.date()
        ).all()
        admin_groups = Group.query.filter(
            Group.admin_id == user_id,
            Group.date_ > datetime.now().date()  # Filter for future groups
        ).all()
        all_groups = list(set(joined_groups + admin_groups))
        self.cache.set(cache_key, all_groups)

        return all_groups

    def get_past_groups(self, user_id):
        cache_key = f"past_groups_{user_id}"
        groups = self.cache.get(cache_key)

        if not groups:
            today = datetime.now()
            joined_groups = db.session.query(Group).join(GroupParticipants).filter(
                GroupParticipants.user_id == user_id,
                Group.date_ < today.date()
            ).all()
            admin_groups = Group.query.filter(
                Group.admin_id == user_id,
                Group.date_ < datetime.now().date()  # Filter for future groups
            ).all()
            all_groups = list(set(joined_groups + admin_groups))
            self.cache.set(cache_key, all_groups)
            return all_groups
        return groups

    def get_participant(self, user_id, group_id):

        participant = GroupParticipants.query.filter_by(user_id=user_id, group_id=group_id).first()

        return participant

    def delete_participants_by_group(self, group_id):
        cache_key = f"group_participants_{group_id}"
        participants = GroupParticipants.query.filter_by(group_id=group_id).all()

        # Delete from the database
        GroupParticipants.query.filter_by(group_id=group_id).delete()

        # Clear related cache
        self.cache.delete(cache_key)

        self.db_session.commit()

    def get_all_groups(self):
        groups = Group.query.all()

        return groups

    def delete_group_participants(self, group):
        try:
            GroupParticipants.query.filter_by(group_id=group.id).delete()
            db.session.delete(group)
            self.db_session.commit()
            self.cache.delete(f"group_{group.id}_participants")  # Invalidate any cached participants
        except Exception as e:
            self.db_session.rollback()
            raise e

    def get_groups_by_admin(self, admin_id):
        return Group.query.filter_by(admin_id=admin_id).all()

    def get_participant_records_by_user(self, user_id):
        return GroupParticipants.query.filter_by(user_id=user_id).all()

    def get_groups_by_facility(self, facility_id):
        return Group.query.filter_by(facility_id=facility_id).all()


class FacilityProxy:
    def __init__(self, db_session, cache):
        self.cache = cache
        self.db_session = db_session

    def get_facility_by_id(self, facility_id):
        facility = Facility.query.get(facility_id)
        return facility

    def add_facility(self, facility):
        self.db_session.add(facility)
        self.db_session.commit()
        self.cache.set(f"facility_{facility.id}", facility)
        return facility

    def delete_facility(self, facility):
        db.session.delete(facility)
        db.session.commit()
        cache.delete(f"facility_{facility.id}")
        cache.delete("all_facilities")

    def get_facilities_dict(self):
        cache_key = "facilities_dict"
        facilities = self.cache.get(cache_key)

        if not facilities:
            facilities = {facility.id: facility for facility in Facility.query.all()}
            self.cache.set(cache_key, facilities)

        return facilities

    def get_all_facilities(self):
        facilities = Facility.query.all()

        return facilities

    def get_facilities_by_sport(self, sport):
        cache_key = f"facilities_sport_{sport}"
        facilities = self.cache.get(cache_key)

        if not facilities:
            facilities = Facility.query.filter(Facility.sports.like(f"%{sport}%")).all()
            self.cache.set(cache_key, facilities)

        return facilities


class ReviewProxy:
    def __init__(self, db_session, cache):
        self.db_session = db_session
        self.cache = cache

    def get_review_by_id(self, review_id):
        cache_key = f"review_{review_id}"
        review = self.cache.get(cache_key)
        if not review:
            review = Review.query.get(review_id)
            self.cache.set(cache_key, review)

        return review

    def add_review(self, review):
        #review = Review(**review_data)
        self.db_session.add(review)
        self.db_session.commit()
        self.cache.set(f"review_{review.id}", review)
        self.cache.delete(f"reviews_for_user_{review.reviewed_id}")
        self.cache.delete("users_ordered_by_behavior")
        return review

    def delete_review(self, review):
        db.session.delete(review)
        db.session.commit()
        self.cache.delete(f"review_{review.id}")
        self.cache.delete(f"reviews_for_user_{review.reviewed_id}")
        self.cache.delete("users_ordered_by_behavior")


    def get_reviews_by_reviewed_id(self, reviewed_id):
        cache_key = f"reviews_for_user_{reviewed_id}"
        reviews = self.cache.get(cache_key)
        if not reviews:
            reviews = Review.query.filter_by(reviewed_id=reviewed_id).all()
            self.cache.set(cache_key, reviews)
        return reviews

    def delete_reviews_by_user(self, user_id):
        Review.query.filter((Review.reviewer_id == user_id) | (Review.reviewed_id == user_id)).delete()
        self.db_session.commit()


class SportProxy:
    def __init__(self, db_session, cache):
        self.db_session = db_session
        self.cache = cache

    def get_sport_by_name(self, sport_name):
        cache_key = f"sport_name_{sport_name}"
        sport = self.cache.get(cache_key)
        if not sport:
            sport = Sport.query.filter_by(name_=sport_name).first()
            self.cache.set(cache_key, sport)
        return sport

    def add_sport(self, new_sport):
        db.session.add(new_sport)
        db.session.commit()

    def get_all_sports(self):
        sports = Sport.query.all()
        return sports

    def get_all_sports_names(self):
        sports = [sport.name_ for sport in Sport.query.all()]
        return sports



user_proxy = UserProxy(db.session, cache)
group_proxy = GroupProxy(db.session, cache)
facility_proxy = FacilityProxy(db.session, cache)
review_proxy = ReviewProxy(db.session, cache)
sport_proxy = SportProxy(db.session, cache)

# Routes
@app.route('/')
def login():
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        email = request.form['email']
        password_ = request.form['password']
        user = user_proxy.get_user_by_email(email)
        if user and bcrypt.check_password_hash(user.password_, password_):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name_ = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        password_ = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        existing_user = user_proxy.get_user_by_email(email)
        if existing_user:
            flash('Email already registered. Please login.', 'error')
            return redirect(url_for('login_page'))
        try:
            new_user = User(name_=name_, email=email, phone=phone, password_=password_)
            user_proxy.add_user(new_user)
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login_page'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
    return render_template('register.html')

@app.route('/update_user_level/<int:user_id>', methods=['POST'])
def update_user_level(user_id):
    user = user_proxy.get_user_by_id(user_id)
    if user:
        #reviews = Review.query.filter_by(reviewed_id=user_id).all()
        reviews = review_proxy.get_reviews_by_reviewed_id(user.id)
        if reviews:
            skill_ratings = [review.rating_skill for review in reviews]
            behavior_ratings = [review.rating_behavior for review in reviews]
            user.level_ = skill_ratings
            user.behavior_ = behavior_ratings
            db.session.commit()
    return redirect(url_for('user_profile', user_id=user_id))

@app.route('/manage_sports', methods=['GET', 'POST'])
def manage_sports():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    current_user = user_proxy.get_user_by_id(session['user_id'])
    if not current_user.is_admin:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        sport_name = request.form['sport_name'].strip()
        if not sport_name:
            flash('Sport name cannot be empty.', 'warning')
        elif sport_proxy.get_sport_by_name(sport_name): #Sport.query.filter_by(name_=sport_name).first():
            flash('This sport already exists.', 'warning')
        else:
            try:
                new_sport = Sport(name_=sport_name)
                sport_proxy.add_sport(new_sport)
                flash(f'Sport "{sport_name}" added successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'error')

    sports = sport_proxy.get_all_sports()
    return render_template('manage_sports.html', sports=sports)


@app.route('/groups', methods=['GET'])
def groups_to_join():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    sport_filter = request.args.get('sport', '')
    date_filter = request.args.get('date', '')
    facility_filter = request.args.get('facility', '')
    groups = group_proxy.get_filtered_groups(sport_filter, date_filter, facility_filter)
    facilities = facility_proxy.get_facilities_dict()
    sports = sport_proxy.get_all_sports_names()
    return render_template('groups_to_join.html', groups=groups, facilities=facilities, sports=sports)



@app.route('/join_group/<int:group_id>', methods=['POST'])
def join_group(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    user_id = session['user_id']
    group = group_proxy.get_group_by_id(group_id)
    if group:
        existing_participant = group_proxy.check_participant_exists(user_id, group_id)

        if existing_participant:
            flash('You have already joined this group.', 'warning')
            return redirect(url_for('dashboard'))

        if group.current_participants < group.max_participants:
            group_proxy.add_participant(user_id, group_id)
            flash('You have successfully joined the group!', 'success')
        else:
            flash('The group is already full.', 'error')
    else:
        flash('Group not found.', 'error')

    return redirect(url_for('dashboard'))


@app.route('/group_details/<int:group_id>', methods=['GET'])
def group_details(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    group = group_proxy.get_group_by_id(group_id)
    if not group:
        flash('Group not found.', 'error')
        return redirect(url_for('dashboard'))

    facility = facility_proxy.get_facility_by_id(group.facility_id)
    participants = group_proxy.get_group_participants(group_id)
    users = [user_proxy.get_user_by_id(participant.user_id) for participant in participants]

    user_admin = user_proxy.get_user_by_id(session['user_id'])
    group_admin = user_proxy.get_user_by_id(group.admin_id)

    return render_template(
        'group_details.html',
        group=group,
        users=users,
        facility=facility,
        user_admin=user_admin,
        group_admin = group_admin
    )


@app.route('/user_profile/<int:user_id>', methods=['GET', 'POST'])
def user_profile(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user = user_proxy.get_user_by_id(user_id)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('dashboard'))

    current_user = user_proxy.get_user_by_id(session['user_id'])

    # Fetch reviews and include the reviewer name
    reviews = review_proxy.get_reviews_by_reviewed_id(user.id)
    review_data = []
    for review in reviews:
        reviewer = user_proxy.get_user_by_id(review.reviewer_id)
        if reviewer:
            review_data.append({
                "id": review.id,
                "reviewer": reviewer.name_,
                "rating_skill": review.rating_skill,
                "rating_behavior": review.rating_behavior,
                "comment": review.comment_ or "No comment provided."
            })

    if request.method == 'POST':
        # Add the new review
        try:
            new_review = Review(
                reviewer_id=session['user_id'],
                reviewed_id=user_id,
                rating_skill=int(request.form['rating_skill']),
                rating_behavior=int(request.form['rating_behavior']),
                comment_=request.form['comment']
            )
            review_proxy.add_review(new_review)

            # Update user stats
            user_proxy.update_user_levels(user_id)

            flash('Review submitted successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error while submitting review: {str(e)}', 'error')

        return redirect(url_for('user_profile', user_id=user_id))

    return render_template('user_profile.html', user=user, current_user=current_user, reviews=review_data)


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    facilities = facility_proxy.get_all_facilities()

    facility_data = [
        {
            "name_": facility.name_,
            "location": facility.location,
            "sports": facility.sports
        }
        for facility in facilities
    ]

    messages = get_flashed_messages(with_categories=True)
    user = user_proxy.get_user_by_id(session['user_id'])
    return render_template('dashboard.html', facilities=facility_data, messages=messages, user=user)


@app.route('/get_facilities/<sport>', methods=['GET'])
def get_facilities(sport):
    facilities = facility_proxy.get_facilities_by_sport(sport)
    facility_data = [{"id": facility.id, "name": facility.name_, "location": facility.location} for facility in facilities]
    return {"facilities": facility_data}



@app.route('/your_groups', methods=['GET'])
def your_groups():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    user_id = session['user_id']
    all_groups = group_proxy.get_groups_by_participant(user_id)
    return render_template('your_groups.html', groups=all_groups)

from datetime import datetime


@app.route('/active_groups', methods=['GET'])
def active_groups():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    all_groups = group_proxy.get_active_groups_by_participant(user_id)
    group_data = [
        {
            'id': group.id,
            'name': group.name_,
            'sport': group.sport,
            'facility_name': group.facility.name_ if group.facility else 'Unknown',
            'date': group.date_,
            'time': group.time_,
        }
        for group in all_groups
    ]
    return render_template('active_groups.html', groups=group_data)


@app.route('/past_groups', methods=['GET'])
def past_groups():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    user_id = session['user_id']
    groups = group_proxy.get_past_groups(user_id)

    # Fetch facilities for display
    facilities = {facility.id: facility for facility in facility_proxy.get_all_facilities()}

    return render_template('past_groups.html', groups=groups, facilities=facilities)


@app.route('/leave_group/<int:group_id>', methods=['POST'])
def leave_group(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    user_id = session['user_id']
    participant = group_proxy.get_participant(user_id, group_id)
    if participant:
        group = group_proxy.get_group_by_id(group_id)
        group.current_participants -= 1  # Decrease participant count
        group_proxy.remove_participant(participant)
        flash('You have successfully left the group.', 'success')
    else:
        flash('You are not a member of this group.', 'error')
    return redirect(url_for('your_groups'))


from datetime import date
@app.route('/create_group', methods=['GET', 'POST'])
def create_group():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    sports = [sport.name_ for sport in sport_proxy.get_all_sports()]
    today_date = date.today().isoformat()  # Get today's date in YYYY-MM-DD format

    if request.method == 'POST':
        name_ = request.form['name']
        sport = request.form['sport']
        facility_id = request.form['facility']
        description_ = request.form['description']
        max_participants = request.form['max_participants']
        date_ = request.form['date_']  # Updated
        time_ = request.form['time_']  # Updated
        price = float(request.form['price'])
        duration = int(request.form['duration'])

        if date_ < today_date:
            flash("The date must be today or in the future.", "warning")
            return redirect(url_for('dashboard'))

        new_group = Group(
            name_=name_,
            sport=sport,
            facility_id=facility_id,
            description_=description_,
            max_participants=max_participants,
            admin_id=session['user_id'],
            date_=date_,  # Updated
            time_=time_,  # Updated
            price=price,
            duration=duration
        )
        try:
            group_proxy.add_group(new_group)
            flash('Group created successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating group: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

    return render_template('create_group.html', sports=sports)


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login_page'))

from functools import wraps

# Helper decorator to check for admin role
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        user = user_proxy.get_user_by_id(user_id)
        if not user or not user.is_admin:
            flash('Access denied. Admins only.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/delete_facility/<int:facility_id>', methods=['POST'])
def delete_facility(facility_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user = user_proxy.get_user_by_id(session['user_id'])
    if not user.is_admin:
        flash("You are not authorized to perform this action.", "danger")
        return redirect(url_for('dashboard'))

    facility = facility_proxy.get_facility_by_id(facility_id)
    if not facility:
        flash("Facility not found.", "danger")
        return redirect(url_for('dashboard'))

    try:

        associated_groups = group_proxy.get_groups_by_facility(facility.id)
        for group in associated_groups:
            group_proxy.delete_group_participants(group)

        facility_proxy.delete_facility(facility)

        flash(f"Facility '{facility.name_}' and its associated activities have been deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while deleting the facility: {str(e)}", "danger")

    return redirect(url_for('manage_facilities'))  # Adjust this route as per your app structure



@app.route('/edit_facility/<int:facility_id>', methods=['GET', 'POST'])
def edit_facility(facility_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user = user_proxy.get_user_by_id(session['user_id'])
    if not user or not user.is_admin:
        flash('You do not have permission to edit facilities.', 'error')
        return redirect(url_for('dashboard'))

    facility = facility_proxy.get_facility_by_id(facility_id)
    if not facility:
        flash('Facility not found.', 'error')
        return redirect(url_for('dashboard'))

    available_sports = [sport.name_ for sport in sport_proxy.get_all_sports()]  # Fetch all available sports

    if request.method == 'POST':
        name_ = request.form['name']
        location = request.form['location']
        sports_input = request.form['sports']

        # Split and clean sports input
        sports_list = [sport.strip() for sport in sports_input.split(',')]

        # Validate sports
        invalid_sports = [sport for sport in sports_list if sport not in available_sports]
        if invalid_sports:
            flash(f"The following sports are invalid: {', '.join(invalid_sports)}", 'error')
            return render_template(
                'edit_facility.html',
                facility=facility,
                available_sports=available_sports,
                name=name_,
                location=location,
                sports_input=sports_input,
            )

        # Update facility
        facility.name_ = name_
        facility.location = location
        facility.sports = ', '.join(sports_list)
        try:
            db.session.commit()
            flash('Facility updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred: {e}', 'error')
        return redirect(url_for('dashboard'))

    return render_template(
        'edit_facility.html',
        facility=facility,
        available_sports=available_sports,
        name=facility.name_,
        location=facility.location,
        sports_input=facility.sports,
    )



# Add Facility
@app.route('/add_facility', methods=['GET', 'POST'])
@admin_required
def add_facility():
    available_sports = [sport.name_ for sport in sport_proxy.get_all_sports()]  # Fetch all available sports

    if request.method == 'POST':
        name_ = request.form['name']
        location = request.form['location']
        sports_input = request.form['sports']

        # Split and clean sports input
        sports_list = [sport.strip() for sport in sports_input.split(',')]

        # Validate sports
        invalid_sports = [sport for sport in sports_list if sport not in available_sports]
        if invalid_sports:
            flash(f"The following sports are invalid: {', '.join(invalid_sports)}", 'error')
            return render_template(
                'add_facility.html',
                available_sports=available_sports,
                name=name_,
                location=location,
                sports_input=sports_input,
            )

        # Add new facility
        new_facility = Facility(name_=name_, location=location, sports=', '.join(sports_list))
        try:
            facility_proxy.add_facility(new_facility)
            flash('Facility added successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding facility: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

    return render_template('add_facility.html', available_sports=available_sports)


@app.route('/delete_review/<int:review_id>/<int:user_id>', methods=['POST'])
def delete_review(review_id, user_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    current_user = user_proxy.get_user_by_id(session['user_id'])
    if not current_user or not current_user.is_admin:
        flash("You are not authorized to perform this action.", "danger")
        return redirect(url_for('dashboard'))

    try:
        review = review_proxy.get_review_by_id(review_id)
        if not review:
            flash("Review not found.", "danger")
            return redirect(url_for('user_profile', user_id=user_id))

        # Delete the review
        review_proxy.delete_review(review)

        # Update user stats
        user_proxy.update_user_levels(user_id)

        flash("Review deleted and player stats updated successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred: {str(e)}", "danger")


    return redirect(url_for('user_profile', user_id=user_id))

@app.route('/manage_groups', methods=['GET', 'POST'])
def manage_groups():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user = user_proxy.get_user_by_id(session['user_id'])
    if not user.is_admin:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('dashboard'))

    groups = group_proxy.get_all_groups()
    return render_template('manage_groups.html', groups=groups)

@app.route('/manage_facilities', methods=['GET'])
def manage_facilities():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user = user_proxy.get_user_by_id(session['user_id'])
    if not user.is_admin:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('dashboard'))

    facilities = facility_proxy.get_all_facilities()  # Fetch all facilities
    return render_template('manage_facilities.html', facilities=facilities)

@app.route('/delete_group/<int:group_id>', methods=['POST'])
def delete_group(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user = user_proxy.get_user_by_id(session['user_id'])
    group = group_proxy.get_group_by_id(group_id)
    if not (user.is_admin or group.admin_id == user.id):
        flash('Unauthorized action.', 'error')
        return redirect(url_for('dashboard'))


    if not group:
        flash('Group not found.', 'error')
        return redirect(url_for('manage_groups'))

    try:
        # Remove all group participants
        group_proxy.delete_group_participants(group)
        flash('Group deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred while deleting the group: {e}', 'error')

    return redirect(url_for('manage_groups'))

@app.route('/remove_member/<int:group_id>/<int:user_id>', methods=['POST'])
def remove_member(group_id, user_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user = user_proxy.get_user_by_id(session['user_id'])

    participant = group_proxy.get_participant(user_id, group_id)
    if not participant:
        flash('Member not found in this group.', 'error')
        return redirect(url_for('group_details', group_id=group_id))

    try:
        group_proxy.remove_participant(participant)
        group = group_proxy.get_group_by_id(group_id)
        if group:
            group.current_participants -= 1
        db.session.commit()
        flash('Member removed from the group.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred while removing the member: {e}', 'error')

    return redirect(url_for('group_details', group_id=group_id))


@app.route('/manage_users', methods=['GET', 'POST'])
def manage_users():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user = user_proxy.get_user_by_id(session['user_id'])
    if not user.is_admin:
        flash("You are not authorized to access this page.", "danger")
        return redirect(url_for('dashboard'))

    users = user_proxy.get_users_ordered_by_behavior()

    return render_template('manage_users.html', users=users)


@app.route('/ban_user/<int:user_id>', methods=['POST'])
def ban_user(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    current_user = user_proxy.get_user_by_id(session['user_id'])
    if not current_user.is_admin:
        flash("You are not authorized to perform this action.", "danger")
        return redirect(url_for('dashboard'))

    user_to_ban = user_proxy.get_user_by_id(user_id)
    if not user_to_ban:
        flash("User not found.", "danger")
        return redirect(url_for('manage_users'))

    try:
        # Delete all groups where the user is an admin
        groups_administered = Group.query.filter_by(admin_id=user_id).all()
        for group in groups_administered:
            # Delete all participants of the group

            group_proxy.delete_group_participants(group)

        # Remove the user from group participants and update participant counts
        groups_as_participant = group_proxy.get_participant_records_by_user(user_id)
        for participant_record in groups_as_participant:
            group = group_proxy.get_group_by_id(participant_record.group_id)
            if group and group.current_participants > 0:
                group.current_participants -= 1
            group_proxy.remove_participant(participant_record)

        # Remove reviews where the user is a reviewer or reviewed
        Review.query.filter((Review.reviewer_id == user_id) | (Review.reviewed_id == user_id)).delete()

        # Finally, delete the user
        user_proxy.delete_user(user_to_ban)

        flash(f"User '{user_to_ban.name_}' and their associated groups have been successfully deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while banning the user: {str(e)}", "danger")

    return redirect(url_for('manage_users'))


if __name__ == '__main__':
    app.run(debug=True)