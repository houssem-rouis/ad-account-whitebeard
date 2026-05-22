from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, TextAreaField, IntegerField, FloatField, SelectField
from wtforms.validators import DataRequired, Length, NumberRange

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class UserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=120)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    is_admin = BooleanField('Administrator')
    submit = SubmitField('Create user')

class AdAccountForm(FlaskForm):
    name = StringField('Account Name', validators=[DataRequired(), Length(max=200)])
    provider = StringField('Provider / Network', validators=[DataRequired(), Length(max=120)])
    submit = SubmitField('Add account')

class AdForm(FlaskForm):
    name = StringField('Ad name', validators=[DataRequired(), Length(max=200)])
    script = TextAreaField('Ad script or copy', validators=[DataRequired(), Length(min=10)])
    impressions = IntegerField('Impressions', validators=[NumberRange(min=0)], default=0)
    clicks = IntegerField('Clicks', validators=[NumberRange(min=0)], default=0)
    spend = FloatField('Spend', validators=[NumberRange(min=0)], default=0.0)
    revenue = FloatField('Revenue', validators=[NumberRange(min=0)], default=0.0)
    status = SelectField('Status', choices=[('running', 'Running'), ('paused', 'Paused'), ('stopped', 'Stopped')])
    submit = SubmitField('Save ad')

class CompetitorForm(FlaskForm):
    name = StringField('Competitor ad name', validators=[DataRequired(), Length(max=200)])
    script = TextAreaField('Competitor copy', validators=[DataRequired(), Length(min=10)])
    status = SelectField('Status', choices=[('running', 'Running'), ('paused', 'Paused')])
    source = StringField('Source or platform', validators=[Length(max=200)])
    submit = SubmitField('Add competitor ad')
