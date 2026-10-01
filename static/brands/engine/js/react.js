'use strict';

var _createClass = function () { function defineProperties(target, props) { for (var i = 0; i < props.length; i++) { var descriptor = props[i]; descriptor.enumerable = descriptor.enumerable || false; descriptor.configurable = true; if ("value" in descriptor) descriptor.writable = true; Object.defineProperty(target, descriptor.key, descriptor); } } return function (Constructor, protoProps, staticProps) { if (protoProps) defineProperties(Constructor.prototype, protoProps); if (staticProps) defineProperties(Constructor, staticProps); return Constructor; }; }();

function _classCallCheck(instance, Constructor) { if (!(instance instanceof Constructor)) { throw new TypeError("Cannot call a class as a function"); } }

function _possibleConstructorReturn(self, call) { if (!self) { throw new ReferenceError("this hasn't been initialised - super() hasn't been called"); } return call && (typeof call === "object" || typeof call === "function") ? call : self; }

function _inherits(subClass, superClass) { if (typeof superClass !== "function" && superClass !== null) { throw new TypeError("Super expression must either be null or a function, not " + typeof superClass); } subClass.prototype = Object.create(superClass && superClass.prototype, { constructor: { value: subClass, enumerable: false, writable: true, configurable: true } }); if (superClass) Object.setPrototypeOf ? Object.setPrototypeOf(subClass, superClass) : subClass.__proto__ = superClass; }

var Clock = function (_React$Component) {
	_inherits(Clock, _React$Component);

	function Clock(props) {
		_classCallCheck(this, Clock);

		var _this = _possibleConstructorReturn(this, (Clock.__proto__ || Object.getPrototypeOf(Clock)).call(this, props));

		_this.state = { date: new Date() };
		return _this;
	}

	_createClass(Clock, [{
		key: 'componentDidMount',
		value: function componentDidMount() {
			var _this2 = this;

			this.timerID = setInterval(function () {
				return _this2.tick();
			}, 1000);
		}
	}, {
		key: 'componentWillUnmount',
		value: function componentWillUnmount() {
			clearInterval(this.timerID);
		}
	}, {
		key: 'tick',
		value: function tick() {
			this.setState({
				date: new Date()
			});
		}
	}, {
		key: 'render',
		value: function render() {
			return React.createElement(
				'span',
				null,
				'Current Time: ',
				this.state.date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
			);
		}
	}]);

	return Clock;
}(React.Component);

var currentReactTime = document.getElementById('currentReactTime');
if (currentReactTime) {
	ReactDOM.render(React.createElement(Clock, null), currentReactTime);
}

//-------------------

var PHPToReactCounter = function (_React$Component2) {
	_inherits(PHPToReactCounter, _React$Component2);

	function PHPToReactCounter(props) {
		_classCallCheck(this, PHPToReactCounter);

		var _this3 = _possibleConstructorReturn(this, (PHPToReactCounter.__proto__ || Object.getPrototypeOf(PHPToReactCounter)).call(this, props));

		_this3.state = { date: '' };
		return _this3;
	}

	_createClass(PHPToReactCounter, [{
		key: 'componentDidMount',
		value: function componentDidMount() {
			var _this4 = this;

			this.timerID = setInterval(function () {
				return _this4.tick();
			}, 1000);
		}
	}, {
		key: 'componentWillUnmount',
		value: function componentWillUnmount() {
			clearInterval(this.timerID);
		}
	}, {
		key: 'tick',
		value: function tick() {
			var daycounter = new Date(this.props.drawdate).getTime() - new Date().getTime();
			this.setState({
				date: daycounter
			});
		}
	}, {
		key: 'render',
		value: function render() {
			var countdownTimer = React.createElement(CountdownToTime, { countdown: new Date(this.props.drawdate).getTime() - new Date().getTime(), drawdateshort: this.props.drawdateshort });
			return React.createElement(
				'span',
				null,
				countdownTimer
			);
		}
	}]);

	return PHPToReactCounter;
}(React.Component);

function CountdownToTime(props) {
	var countdown = props.countdown;
	var drawDay = props.drawdateshort;
	if (!isNaN(countdown) && countdown >= 0) {
		var days = Math.floor(countdown / (1000 * 60 * 60 * 24));
		var hours = Math.floor(countdown % (1000 * 60 * 60 * 24) / (1000 * 60 * 60));
		var minutes = Math.floor(countdown % (1000 * 60 * 60) / (1000 * 60));
		var seconds = Math.floor(countdown % (1000 * 60) / 1000);
		var counter = void 0;
		if (drawDay == 1) {
			if (days > 1) {
				counter = days + " days";
			} else if (days == 1) {
				counter = days + " day";
			} else {
				counter = hours + ":" + (minutes > 10 ? "" : "0") + minutes + ":" + (seconds > 10 ? "" : "0") + seconds;
			}
		} else {
			counter = days + " Day(s) " + hours + ":" + (minutes < 10 ? '0' : '') + minutes + ":" + (seconds < 10 ? '0' : '') + seconds;
		}
		return counter;
	}
	return "To Be Announced";
}

// Only mount the React counter on elements that actually provide a
// data-drawdate. Elements without it (e.g. server-rendered `.wl-countdown`
// spans ticked by the global countdown in base.html) must be left alone,
// otherwise React clobbers them with "To Be Announced".
var dates = document.getElementsByClassName("lottoTicketCounter");
for (var i = 0; i < dates.length; i++) {
	var dateEl = dates[i];
	if (!dateEl || !dateEl.dataset || !dateEl.dataset.drawdate) continue;
	ReactDOM.render(React.createElement(PHPToReactCounter, dateEl.dataset), dateEl);
}

var lottoBannerDate = document.getElementById("drawCounterReact");
if (lottoBannerDate && lottoBannerDate.dataset && lottoBannerDate.dataset.drawdate) {
	ReactDOM.render(React.createElement(PHPToReactCounter, lottoBannerDate.dataset), lottoBannerDate);
}

var lottoCheckboxDates = document.getElementsByClassName("drawDateCountdownReact");
for (var i = 0; i < lottoCheckboxDates.length; i++) {
	var checkboxEl = lottoCheckboxDates[i];
	if (!checkboxEl || !checkboxEl.dataset || !checkboxEl.dataset.drawdate) continue;
	ReactDOM.render(React.createElement(PHPToReactCounter, checkboxEl.dataset), checkboxEl);
}

//----------------------------

var PHPToReactTimeOnSite = function (_React$Component3) {
	_inherits(PHPToReactTimeOnSite, _React$Component3);

	function PHPToReactTimeOnSite(props) {
		_classCallCheck(this, PHPToReactTimeOnSite);

		var _this5 = _possibleConstructorReturn(this, (PHPToReactTimeOnSite.__proto__ || Object.getPrototypeOf(PHPToReactTimeOnSite)).call(this, props));

		_this5.state = { date: parseInt(_this5.props.drawdate, 10) || 0 };
		return _this5;
	}

	_createClass(PHPToReactTimeOnSite, [{
		key: 'componentDidMount',
		value: function componentDidMount() {
			var _this6 = this;

			this.timerID = setInterval(function () {
				return _this6.tick();
			}, 1000);
		}
	}, {
		key: 'componentWillUnmount',
		value: function componentWillUnmount() {
			clearInterval(this.timerID);
		}
	}, {
		key: 'tick',
		value: function tick() {
			this.setState(function (state) {
				return {
					date: state.date + 1
				};
			});
		}
	}, {
		key: 'render',
		value: function render() {
			var countdownTimer = React.createElement(FormatTimeOnSite, { countdown: this.state.date });
			return React.createElement(
				'span',
				null,
				'Current Session: ',
				countdownTimer
			);
		}
	}]);

	return PHPToReactTimeOnSite;
}(React.Component);

function FormatTimeOnSite(props) {
	var countdown = props.countdown;
	var hours = Math.floor(countdown / 3600);
	var minutes = Math.floor(countdown / 60) % 60;
	var seconds = countdown % 60;
	return [hours, minutes, seconds].map(function (v) {
		return ('' + v).padStart(2, '0');
	}) // (''+v) puts a space in front of v so that you can add a 0 in the first position with padStart ('5' would become ' 5' and padStart add a 0 in the empty space)
	//.filter((v,i) => v !== '00' || i > 0)
	.join(':');
}

var timeOnsite = document.getElementById("timeOnSiteCounter");
if (timeOnsite) {
	ReactDOM.render(React.createElement(PHPToReactTimeOnSite, timeOnsite.dataset), document.getElementById('displayTimeOnSite'));
	ReactDOM.render(React.createElement(PHPToReactTimeOnSite, timeOnsite.dataset), document.getElementById('displayTimeOnSiteM'));
}